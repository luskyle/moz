import * as path from 'path';
import * as vscode from 'vscode';
import { buildBackend, dumpModel, findLibSo, findPyDir, isBundledBackend } from './backend';

/** CustomEditor 的 viewType：资源管理器里双击 .dxf/.dwg 就直接进这个看图编辑器。 */
const VIEW_TYPE = 'mozDxfViewer.editor';

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
  /* 自定义编辑器（可交互看图）：点击/双击 *.dxf、*.dwg 文件直接出现图纸。
     priority: "default" = 这类文件的默认编辑器（想看原文随时 Open With… → Text Editor）。 */
  const provider: vscode.CustomReadonlyEditorProvider<vscode.CustomDocument> = {
    openCustomDocument(uri: vscode.Uri): vscode.CustomDocument {
      return { uri, dispose: () => undefined };
    },
    async resolveCustomEditor(
      document: vscode.CustomDocument,
      panel: vscode.WebviewPanel,
    ): Promise<void> {
      panel.webview.options = {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
      };
      panel.webview.html = viewHtml(context, panel);
      await render(context, panel, document.uri);
    },
  };
  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(VIEW_TYPE, provider, {
      supportsMultipleEditorsPerDocument: true,
    }),
  );

  /* 右键菜单 / 命令面板：同一件事，只是走 openWith 打开同一个编辑器。 */
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
      void vscode.commands.executeCommand('vscode.openWith', uri, VIEW_TYPE);
    }),
  );
}

/** 当前主题要深色画布吗（Dark/HighContrast → 后端按浅线配色，压着深灰底才看得见）。 */
function isDarkTheme(): boolean {
  const kind = vscode.window.activeColorTheme.kind;
  return kind === vscode.ColorThemeKind.Dark || kind === vscode.ColorThemeKind.HighContrast;
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
        '找不到渲染后端（python/moz_cadview.py）。\n\n' +
          '扩展自带后端缺失（python/ 没打进去？），或 repo 的 py/ 不在工作区。\n' +
          '可在设置 mozDxfViewer.backendPyDir 里指定仓库的 py/ 目录。',
      );
    }
    const dark = isDarkTheme();                  // 线色按画布深浅出：黑线压深灰底 = 看不见
    const model = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: '读取图纸 ' + name + '…',
      },
      async () => {
        if (!findLibSo(pyDir)) {
          if (isBundledBackend(context, pyDir)) {
            throw new Error(
              '扩展自带的 libmozcadio.so 缺失或平台不匹配（当前打包的是 ' +
                process.platform +
                ' 版）。\n\n请重新下载对应平台的 vsix，或用仓库后端：' +
                'bash scripts/build_moz_cadio.sh 后在设置里指定 backendPyDir。',
            );
          }
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
        return dumpModel(pyDir, uri.fsPath, dark);
      },
    );
    void panel.webview.postMessage({ type: 'model', name, json: model });
  } catch (error) {
    void panel.webview.postMessage({
      type: 'error',
      error: String(error instanceof Error ? error.message : error),
    });
  }
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
  <canvas id="canvas"></canvas>
  <div id="layers">
    <div class="layers-head">图层
      <button id="layers-all" title="全部显示">全部</button>
      <button id="layers-none" title="全部隐藏">隐藏</button>
    </div>
    <div id="layers-list"></div>
  </div>
  <div id="tooltip"></div>
  <div id="status">…</div>
  <div id="hint">滚轮缩放 · 拖动平移 · 双击还原 · 悬停/点选图元</div>
</div>
<pre id="error" hidden></pre>
<script src="${script}"></script>
</body>
</html>`;
}

export function deactivate(): void {
  // 编辑器随 webview 关闭自行释放
}