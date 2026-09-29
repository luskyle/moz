import * as childProcess from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

/** .so 的平台文件名 */
function libName(): string {
  if (process.platform === 'darwin') {
    return 'libmozcadio.dylib';
  }
  if (process.platform === 'win32') {
    return 'mozcadio.dll';
  }
  return 'libmozcadio.so';
}

/**
 * 找出渲染后端的 py/ 目录（含 moz_cadview.py / moz_cadio.py）。
 * 顺序：设置 > 工作区里的仓库根 > 扩展所在仓库（开发模式 F5 即工作）。
 */
export function findPyDir(context: vscode.ExtensionContext): string | undefined {
  const configured = vscode.workspace
    .getConfiguration('mozDxfViewer')
    .get<string>('backendPyDir', '');
  if (configured && fs.existsSync(path.join(configured, 'moz_cadview.py'))) {
    return path.resolve(configured);
  }
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const candidate = path.join(folder.uri.fsPath, 'py');
    if (fs.existsSync(path.join(candidate, 'moz_cadview.py'))) {
      return candidate;
    }
  }
  const dev = path.resolve(context.extensionPath, '..', '..', '..', 'py');
  if (fs.existsSync(path.join(dev, 'moz_cadview.py'))) {
    return dev;
  }
  return undefined;
}

/** 已构建的 libmozcadio.so 路径（build/lib 或随包位置） */
export function findLibSo(pyDir: string): string | undefined {
  const candidates = [
    path.join(pyDir, '..', 'build', 'lib', libName()),
    path.join(pyDir, 'moz_data', 'lib', libName()),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

/** 跑一个子进程；非零退出码抛错（带 stderr）。 */
function run(
  command: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = childProcess.spawn(command, args, { cwd, env });
    let stderr = '';
    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on('error', (error) => reject(error));
    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(stderr.trim() || `进程退出码 ${code}`));
      }
    });
  });
}

/** 编译 libmozcadio.so（第一次要一两分钟；里面有 cmake + g++ 就行） */
export async function buildBackend(pyDir: string): Promise<void> {
  const repoRoot = path.dirname(pyDir);
  const script = path.join(repoRoot, 'scripts', 'build_moz_cadio.sh');
  if (!fs.existsSync(script)) {
    throw new Error(`找不到构建脚本：${script}`);
  }
  await run(script, [], repoRoot, { ...process.env, PYTHONPATH: pyDir });
}

/**
 * 把一张 DXF/DWG 导出成 **浅色 SVG**（黑线白底，Webview 里最易读）。
 * 通过 `python -m moz_cadview <图> --export-svg <临时文件> --light` 实现；
 * 需要 PySide6 与已构建的 libmozcadio.so，都在 README 里写清了。
 */
export async function exportSvg(pyDir: string, drawingPath: string): Promise<string> {
  const interpreter = vscode.workspace
    .getConfiguration('mozDxfViewer')
    .get<string>('python', 'python3');
  const soFile = findLibSo(pyDir);
  const tmpSvg = path.join(os.tmpdir(), `moz-dxf-view-${Date.now()}.svg`);
  const args = [
    '-m',
    'moz_cadview',
    drawingPath,
    '--export-svg',
    tmpSvg,
    '--light',
    '--width',
    '1800',
    '--height',
    '1400',
  ];
  const env: NodeJS.ProcessEnv = { ...process.env, QT_QPA_PLATFORM: 'offscreen' };
  if (soFile) {
    env.MOZ_CADIO_LIB = soFile;
  }
  try {
    await run(interpreter, args, pyDir, env);
    return await fs.promises.readFile(tmpSvg, 'utf-8');
  } finally {
    await fs.promises.rm(tmpSvg, { force: true });
  }
}