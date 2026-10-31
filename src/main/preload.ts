import { contextBridge, ipcRenderer, webUtils } from "electron";

import type {
  AppInfo,
  DesktopApi,
  RecoveryRequest,
  RecoveryResult,
} from "../shared/types";

const api: DesktopApi = {
  info: () => ipcRenderer.invoke("app:info") as Promise<AppInfo>,

  pickVideo: () => ipcRenderer.invoke("dialog:pick-video") as Promise<string | null>,

  pathForFile: (file: File) => webUtils.getPathForFile(file),

  recover: (request: RecoveryRequest) =>
    ipcRenderer.invoke("recovery:start", request) as Promise<RecoveryResult>,

  cancel: () => ipcRenderer.invoke("recovery:cancel") as Promise<boolean>,

  openPath: (target: string) =>
    ipcRenderer.invoke("shell:open-path", target) as Promise<string>,

  showInFolder: (target: string) =>
    ipcRenderer.invoke("shell:show-in-folder", target) as Promise<void>,

  copyText: (text: string) =>
    ipcRenderer.invoke("shell:copy-text", text) as Promise<void>,

  onProgress: (listener: (message: string) => void) => {
    const handler = (_event: unknown, message: string) => listener(message);
    ipcRenderer.on("recovery:progress", handler);
    return () => ipcRenderer.removeListener("recovery:progress", handler);
  },
};

contextBridge.exposeInMainWorld("nvidiaFix", api);
