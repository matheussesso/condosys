// Bridge between the page (no Node access) and the main process.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("condosys", {
  apiInfo: () => ipcRenderer.invoke("api:info"),
  onApiReady: (callback) => ipcRenderer.on("api:ready", (_event, info) => callback(info)),
  onApiFailed: (callback) => ipcRenderer.on("api:failed", (_event, message) => callback(message)),
  pickCertificate: () => ipcRenderer.invoke("dialog:pick-certificate"),
  openFile: (filePath) => ipcRenderer.invoke("shell:open", filePath),
  showInFolder: (filePath) => ipcRenderer.invoke("shell:show", filePath),
});
