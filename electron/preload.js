const { contextBridge, ipcRenderer } = require('electron');

// Minimal native-window bridge — everything else the renderer needs goes
// through the Python backend's HTTP API directly (same-origin fetch).
contextBridge.exposeInMainWorld('desktop', {
  resizeWindow: (view) => ipcRenderer.invoke('resize-window', view),
  forceToFront: () => ipcRenderer.invoke('force-to-front'),
  signIn: () => ipcRenderer.invoke('sign-in'),
  quit: () => ipcRenderer.invoke('quit'),
});
