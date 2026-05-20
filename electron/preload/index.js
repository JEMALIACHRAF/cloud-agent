const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  getCredentials: () => ipcRenderer.invoke("get-credentials"),
  openExternal:   (url) => ipcRenderer.invoke("open-external", url),
  platform:       process.platform,
});
