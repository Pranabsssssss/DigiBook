// DigiBook Dashboard Scripts

async function createNewWhiteboard() {
    try {
        const title = prompt('Enter a title for the new whiteboard:', 'Untitled');
        if (title === null) return; // User cancelled

        const res = await API.post('/api/v1/whiteboards', { title: title.trim() || 'Untitled' });
        if (res.success && res.whiteboard) {
            window.location.href = `/whiteboard/${res.whiteboard.id}`;
        }
    } catch (err) {
        alert('Failed to create whiteboard: ' + err.message);
    }
}

async function deleteWhiteboard(event, wbId) {
    event.stopPropagation(); // Prevent opening whiteboard card
    if (!confirm('Are you sure you want to delete this whiteboard?')) {
        return;
    }
    try {
        await API.delete(`/api/v1/whiteboards/${wbId}`);
        window.location.reload();
    } catch (err) {
        alert('Failed to delete whiteboard: ' + err.message);
    }
}
