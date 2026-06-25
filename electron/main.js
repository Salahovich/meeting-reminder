const path = require('path');
const readline = require('readline');
const { spawn } = require('child_process');
const { app, BrowserWindow, ipcMain, screen } = require('electron');

// Sizes ported verbatim from the old webui.py (IDLE_SIZE/TODAY_SIZE/ALERT_SIZE/
// MARGIN_X/MARGIN_Y) — positioning logic moved here since Electron's `screen`
// module is cross-platform and DPI-correct out of the box (no ctypes needed).
const SIZES = {
  idle: { width: 380, height: 64 },
  today: { width: 380, height: 530 },
  alert: { width: 380, height: 300 },
};
const MARGIN_X = 24;
const MARGIN_Y = 70;

const REDIRECT_PREFIX = 'https://login.microsoftonline.com/common/oauth2/nativeclient';

let mainWindow = null;
let pythonProcess = null;
let backendPort = null;
let currentView = 'idle';

function bottomRightPosition(width, height) {
  const { workArea } = screen.getPrimaryDisplay();
  return {
    x: workArea.x + workArea.width - width - MARGIN_X,
    y: workArea.y + workArea.height - height - MARGIN_Y,
  };
}

function pythonExecutablePath(projectRoot) {
  return process.platform === 'win32'
    ? path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(projectRoot, '.venv', 'bin', 'python');
}

function startPythonBackend(projectRoot) {
  return new Promise((resolve, reject) => {
    const pythonExe = pythonExecutablePath(projectRoot);
    // Force UTF-8 mode: without it, this Python build decodes .py source
    // files using the Windows locale codepage (cp1252 here), silently
    // mangling non-ASCII literals (e.g. en-dashes) into U+FFFD.
    pythonProcess = spawn(pythonExe, ['run.py'], {
      cwd: projectRoot,
      env: { ...process.env, PYTHONUTF8: '1' },
    });

    let resolved = false;
    const rl = readline.createInterface({ input: pythonProcess.stdout });
    rl.on('line', (line) => {
      console.log(`[backend] ${line}`);
      const match = line.match(/^PORT=(\d+)/);
      if (match && !resolved) {
        resolved = true;
        resolve(parseInt(match[1], 10));
      }
    });
    pythonProcess.stderr.on('data', (data) => {
      console.error(`[backend:stderr] ${data}`);
    });
    pythonProcess.on('error', (err) => {
      if (!resolved) reject(err);
    });
    pythonProcess.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`);
      if (!resolved) reject(new Error(`Python backend exited (code ${code}) before reporting a port`));
    });
  });
}

function killPythonProcess() {
  if (pythonProcess && !pythonProcess.killed) {
    pythonProcess.kill();
  }
}

function createMainWindow(port) {
  const { width, height } = SIZES.idle;
  const { x, y } = bottomRightPosition(width, height);
  mainWindow = new BrowserWindow({
    width,
    height,
    x,
    y,
    frame: false,
    resizable: true,
    minWidth: width,
    maxWidth: width, // width is fixed — only the height is meant to be user-adjustable
    minHeight: SIZES.idle.height,
    alwaysOnTop: false,
    backgroundColor: '#0a0a0a',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      autoplayPolicy: 'no-user-gesture-required',
    },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);

  // Remember a manual height adjustment for whichever view is currently shown,
  // so re-opening that view later uses the user's preferred height instead of
  // snapping back to the original default.
  mainWindow.on('resize', () => {
    if (!mainWindow) return;
    const [, height] = mainWindow.getSize();
    SIZES[currentView] = { ...SIZES[currentView], height };
  });
}

function openSignInPopup(url) {
  const popup = new BrowserWindow({
    width: 480,
    height: 640,
    parent: mainWindow,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  popup.setMenuBarVisibility(false);
  popup.loadURL(url);

  let handled = false;
  const handleNavigation = (navUrl) => {
    if (handled || !navUrl.startsWith(REDIRECT_PREFIX)) return;
    const parsed = new URL(navUrl);
    const code = parsed.searchParams.get('code');
    handled = true;
    popup.destroy();
    if (code) {
      fetch(`http://127.0.0.1:${backendPort}/api/auth/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      }).catch((err) => console.error('auth complete request failed', err));
    } else {
      console.error('Sign-in redirect had no code param:', navUrl);
    }
  };

  popup.webContents.on('will-redirect', (_event, navUrl) => handleNavigation(navUrl));
  popup.webContents.on('did-navigate', (_event, navUrl) => handleNavigation(navUrl));
}

ipcMain.handle('resize-window', (_event, view) => {
  currentView = SIZES[view] ? view : 'idle';
  const size = SIZES[currentView];
  const { x, y } = bottomRightPosition(size.width, size.height);
  if (mainWindow) mainWindow.setBounds({ x, y, width: size.width, height: size.height });
});

ipcMain.handle('force-to-front', () => {
  if (!mainWindow) return;
  mainWindow.setAlwaysOnTop(true);
  setTimeout(() => {
    if (mainWindow) mainWindow.setAlwaysOnTop(false);
  }, 500);
});

ipcMain.handle('sign-in', async () => {
  try {
    const res = await fetch(`http://127.0.0.1:${backendPort}/api/auth/url`);
    const { url } = await res.json();
    openSignInPopup(url);
  } catch (err) {
    console.error('sign-in failed', err);
  }
});

ipcMain.handle('quit', () => {
  killPythonProcess();
  app.quit();
});

app.whenReady().then(async () => {
  const projectRoot = path.join(__dirname, '..');
  try {
    backendPort = await startPythonBackend(projectRoot);
    createMainWindow(backendPort);
  } catch (err) {
    console.error('Failed to start Python backend:', err);
    app.quit();
  }
});

app.on('before-quit', () => {
  killPythonProcess();
});

app.on('window-all-closed', () => {
  killPythonProcess();
  app.quit();
});
