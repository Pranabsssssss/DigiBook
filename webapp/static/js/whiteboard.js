// DigiBook Web Whiteboard Client Engine

class WebWhiteboardClient {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.whiteboardId = document.querySelector('meta[name="whiteboard-id"]')?.content;

        // Stroke storage in normalized coordinates
        this.strokes = [];
        this.currentStroke = null;
        this.isDrawing = false;

        // Active tool settings
        this.activeTool = 'pen';
        this.activeColor = '#FFFFFF';
        this.activeWidth = 0.004;

        // Viewport (Zoom & Pan)
        this.zoomLevel = 1.0;
        this.centerX = 0.5;
        this.centerY = 0.5;

        // Setup events
        this.setupEventListeners();
        this.loadWhiteboard();

        // Auto-save timer (every 30 seconds)
        this.autoSaveInterval = setInterval(() => this.saveWhiteboard(true), 30000);
    }

    setupEventListeners() {
        const getCanvasNormalized = (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;

            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;

            const pixelX = (clientX - rect.left) * scaleX;
            const pixelY = (clientY - rect.top) * scaleY;

            // Convert to normalized coordinates via Viewport
            const spanW = 1.0 / this.zoomLevel;
            const spanH = 1.0 / this.zoomLevel;
            const left = Math.max(0, Math.min(1.0 - spanW, this.centerX - spanW / 2.0));
            const top = Math.max(0, Math.min(1.0 - spanH, this.centerY - spanH / 2.0));

            const normX = left + (pixelX / this.canvas.width) * spanW;
            const normY = top + (pixelY / this.canvas.height) * spanH;

            return {
                x: Math.max(0, Math.min(1.0, normX)),
                y: Math.max(0, Math.min(1.0, normY))
            };
        };

        const onDown = (e) => {
            e.preventDefault();
            this.isDrawing = true;
            const pt = getCanvasNormalized(e);
            this.currentStroke = {
                version: 1,
                tool: this.activeTool,
                color: this.activeTool === 'eraser' ? '#000000' : this.activeColor,
                width: this.activeTool === 'eraser' ? 0.025 : this.activeWidth,
                points: [{ x: pt.x, y: pt.y, t: 0 }]
            };
            this.render();
        };

        const onMove = (e) => {
            if (!this.isDrawing || !this.currentStroke) return;
            e.preventDefault();
            const pt = getCanvasNormalized(e);
            this.currentStroke.points.push({ x: pt.x, y: pt.y, t: Date.now() });
            this.render();
        };

        const onUp = (e) => {
            if (!this.isDrawing) return;
            e.preventDefault();
            this.isDrawing = false;
            if (this.currentStroke && this.currentStroke.points.length > 0) {
                this.strokes.push(this.currentStroke);
            }
            this.currentStroke = null;
            this.render();
            this.markUnsaved();
        };

        this.canvas.addEventListener('mousedown', onDown);
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);

        this.canvas.addEventListener('touchstart', onDown, { passive: false });
        window.addEventListener('touchmove', onMove, { passive: false });
        window.addEventListener('touchend', onUp, { passive: false });
    }

    async loadWhiteboard() {
        if (!this.whiteboardId) return;
        try {
            const data = await API.get(`/api/v1/whiteboards/${this.whiteboardId}`);
            if (data.whiteboard && data.whiteboard.strokes) {
                this.strokes = data.whiteboard.strokes;
                this.render();
            }
        } catch (err) {
            console.error('Failed to load whiteboard:', err);
        }
    }

    render() {
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;

        // Clear background to pure black
        ctx.fillStyle = '#000000';
        ctx.fillRect(0, 0, w, h);

        const spanW = 1.0 / this.zoomLevel;
        const spanH = 1.0 / this.zoomLevel;
        const left = Math.max(0, Math.min(1.0 - spanW, this.centerX - spanW / 2.0));
        const top = Math.max(0, Math.min(1.0 - spanH, this.centerY - spanH / 2.0));

        const toPixel = (normPt) => ({
            x: ((normPt.x - left) / spanW) * w,
            y: ((normPt.y - top) / spanH) * h
        });

        const allStrokes = this.currentStroke ? [...this.strokes, this.currentStroke] : this.strokes;

        for (const stroke of allStrokes) {
            if (!stroke.points || stroke.points.length === 0) continue;

            ctx.strokeStyle = stroke.tool === 'eraser' ? '#000000' : stroke.color;
            ctx.fillStyle = ctx.strokeStyle;
            ctx.lineWidth = Math.max(1, stroke.width * h * this.zoomLevel);
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';

            const pts = stroke.points.map(toPixel);

            if (pts.length === 1) {
                ctx.beginPath();
                ctx.arc(pts[0].x, pts[0].y, ctx.lineWidth / 2, 0, Math.PI * 2);
                ctx.fill();
            } else {
                ctx.beginPath();
                ctx.moveTo(pts[0].x, pts[0].y);
                for (let i = 1; i < pts.length; i++) {
                    ctx.lineTo(pts[i].x, pts[i].y);
                }
                ctx.stroke();
            }
        }
    }

    markUnsaved() {
        const status = document.getElementById('saveStatus');
        if (status) {
            status.textContent = 'Unsaved changes';
            status.style.color = '#FFE600';
        }
    }

    async saveWhiteboard(isAutoSave = false) {
        if (!this.whiteboardId) return;
        const status = document.getElementById('saveStatus');
        if (status) status.textContent = isAutoSave ? 'Auto-saving...' : 'Saving...';

        try {
            // Generate small thumbnail for dashboard card
            const thumbCanvas = document.createElement('canvas');
            thumbCanvas.width = 240;
            thumbCanvas.height = 135;
            const tCtx = thumbCanvas.getContext('2d');
            tCtx.drawImage(this.canvas, 0, 0, 240, 135);
            const thumbB64 = thumbCanvas.toDataURL('image/png');

            await API.put(`/api/v1/whiteboards/${this.whiteboardId}/strokes`, {
                strokes: this.strokes,
                thumbnail_b64: thumbB64
            });

            if (status) {
                status.textContent = 'All changes saved';
                status.style.color = '#00F0FF';
            }
        } catch (err) {
            console.error('Failed to save whiteboard:', err);
            if (status) {
                status.textContent = 'Error saving';
                status.style.color = '#FF3366';
            }
        }
    }
}

// Global UI handler bindings
let client = null;

window.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('whiteboardCanvas');
    if (canvas) {
        client = new WebWhiteboardClient(canvas);
    }
});

function setTool(toolName) {
    if (!client) return;
    client.activeTool = toolName;
    document.querySelectorAll('.btn-tool').forEach(b => b.classList.remove('active'));
    if (toolName === 'pen') {
        document.getElementById('toolPen')?.classList.add('active');
    } else {
        document.getElementById('toolEraser')?.classList.add('active');
    }
}

function setColor(hex, el) {
    if (!client) return;
    client.activeColor = hex;
    setTool('pen');
    document.querySelectorAll('.color-dot').forEach(d => d.classList.remove('active'));
    if (el) el.classList.add('active');
}

function zoomIn() {
    if (!client) return;
    client.zoomLevel = Math.min(8.0, client.zoomLevel * 1.25);
    client.render();
}

function zoomOut() {
    if (!client) return;
    client.zoomLevel = Math.max(1.0, client.zoomLevel / 1.25);
    if (client.zoomLevel === 1.0) {
        client.centerX = 0.5;
        client.centerY = 0.5;
    }
    client.render();
}

function resetZoom() {
    if (!client) return;
    client.zoomLevel = 1.0;
    client.centerX = 0.5;
    client.centerY = 0.5;
    client.render();
}

function clearCanvas() {
    if (!client) return;
    if (confirm('Clear the entire canvas?')) {
        client.strokes = [];
        client.render();
        client.markUnsaved();
    }
}

function saveWhiteboard() {
    if (client) client.saveWhiteboard(false);
}

async function saveWhiteboardTitle() {
    const input = document.getElementById('wbTitleInput');
    const wbId = document.querySelector('meta[name="whiteboard-id"]')?.content;
    if (!input || !wbId) return;

    try {
        await API.put(`/api/v1/whiteboards/${wbId}`, { title: input.value.trim() });
    } catch (err) {
        alert('Failed to update title: ' + err.message);
    }
}
