import * as path from 'path';
import * as vscode from 'vscode';
import { buildBackend, exportSvg, findLibSo, findPyDir } from './backend';

/** 每张图纸一个面板：重复打开同一张就复用（rear view），不叠加。 */
const PANELS = new Map<string, vscode.WebviewPanel>();

/** 命令参数可能来自资源管理器（Uri）、编辑器上下文（TextEditor）或什么都没有。 */
function resolveTarget(arg?: unknown): vscode.Uri | undefined {
  if (arg instanceof vscode.Uri) {
    return arg;
  }
  if (arg && typeof arg === 'object' && 'uri' in (arg as object)) {
    const uri = (arg as { uri?: unknown }).uri;
    if (uri instanceof vscode.Uri) {
      return uri;
    }
  }
  return vscode.window.activeTextEditor?.document.uri;
}

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand('mozDxfViewer.show', (arg?: unknown) => {
      const uri = resolveTarget(arg);
      if (!uri) {
        void vscode.window.showInformationMessage(
          '先在资源管理器或编辑器里选中一个 DXF/DWG 文件，再执行「Moz: 查看 DXF/DWG 图纸」。',
        );
        return;
      }
      if (!/\.(dxf|dwg)$/i.test(uri.path)) {
        void vscode.window.showWarningMessage(`${path.basename(uri.path)} 不是 DXF/DWG 文件。`);
        return;
      }
      void openViewer(context, uri);
    }),
  );
}

async function openViewer(context: vscode.ExtensionContext, uri: vscode.Uri): Promise<void> {
  const key = uri.toString();
  const existing = PANELS.get(key);
  if (existing) {
    existing.reveal(vscode.ViewColumn.Beside);
    return;
  }

  const panel = vscode.window.createWebviewPanel(
    'mozDxfViewer',
    path.basename(uri.path),
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
    },
  );
  PANELS.set(key, panel);
  panel.onDidDispose(() => PANELS.delete(key));
  panel.webview.html = viewHtml(context, panel);
  await render(context, panel, uri);
}

async function render(
  context: vscode.ExtensionContext,
  panel: vscode.WebviewPanel,
  uri: vscode.Uri,
): Promise<void> {
  const name = path.basename(uri.path);
  try {
    const pyDir = findPyDir(context);
    if (!pyDir) {
      throw new Error(
        '找不到渲染后端（py/moz_cadview.py）。\n\n' +
          '扩展需要在 moz 仓库的检出环境里跑：把仓库根作为 VS Code 工作区打开，\n' +
          '或在设置 mozDxfViewer.backendPyDir 里指定仓库的 py/ 目录。',
      );
    }
    const svg = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: '渲染 ' + name + '…',
      },
      async () => {
        if (!findLibSo(pyDir)) {
          const shouldBuild = vscode.workspace
            .getConfiguration('mozDxfViewer')
            .get<boolean>('buildBackend', true);
          if (!shouldBuild) {
            throw new Error(
              '缺少 libmozcadio.so。\n\n请先在仓库根跑：bash scripts/build_moz_cadio.sh\n' +
                '（或在设置 mozDxfViewer.buildBackend 打开自动构建）',
            );
          }
          await buildBackend(pyDir);
        }
        return exportSvg(pyDir, uri.fsPath);
      },
    );
    post(panel, { type: 'svg', svg, name });
  } catch (error) {
    post(panel, { type: 'error', error: String(error instanceof Error ? error.message : error) });
  }
}

function post(panel: vscode.WebviewPanel, message: unknown): void {
  void panel.webview.postMessage(message);
}

function viewHtml(context: vscode.ExtensionContext, panel: vscode.WebviewPanel): string {
  const script = panel.webview.asWebviewUri(
    vscode.Uri.joinPath(context.extensionUri, 'media', 'viewer.js'),
  );
  const style = panel.webview.asWebviewUri(
    vscode.Uri.joinPath(context.extensionUri, 'media', 'viewer.css'),
  );
  const csp = [
    "default-src 'none'",
    `style-src ${panel.webview.cspSource} 'unsafe-inline'`,
    `script-src ${panel.webview.cspSource}`,
    'img-src data:',
  ].join('; ');
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<link rel="stylesheet" href="${style}" />
<title>DXF/DWG 图纸</title>
</head>
<body>
<div id="stage">
  <div id="art"></div>
  <div id="status"></div>
  <div id="hint"></div>
</div>
<pre id="error" hidden></pre>
<script src="${script}"></script>
</body>
</html>`;
}

export function deactivate(): void {
  // 面板会随 webview 关闭自行释放
}