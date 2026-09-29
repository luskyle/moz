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
 * 顺序：扩展自带 python/（打进 vsix，装好即用）> 设置 > 工作区里的仓库根 > 开发路径。
 */
export function findPyDir(context: vscode.ExtensionContext): string | undefined {
  const bundled = path.join(context.extensionPath, 'python');
  if (fs.existsSync(path.join(bundled, 'moz_cadview.py'))) {
    return bundled;
  }
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

/** 已构建的 libmozcadio.so 路径（扩展自带 python/moz_data/lib，或仓库 build/lib） */
export function findLibSo(pyDir: string): string | undefined {
  const candidates = [
    path.join(pyDir, 'moz_data', 'lib', libName()),
    path.join(pyDir, '..', 'build', 'lib', libName()),
    path.join(pyDir, libName()),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

/** 当前 pyDir 是否是扩展自带的 python/ 目录 */
export function isBundledBackend(context: vscode.ExtensionContext, pyDir: string): boolean {
  return path.resolve(pyDir) === path.resolve(path.join(context.extensionPath, 'python'));
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

/** 编译 libmozcadio.so（第一次要一两分钟；里面有 cmake + g++ 就行；仅"用仓库后端"时需要） */
export async function buildBackend(pyDir: string): Promise<void> {
  const repoRoot = path.dirname(pyDir);
  const script = path.join(repoRoot, 'scripts', 'build_moz_cadio.sh');
  if (!fs.existsSync(script)) {
    throw new Error(`找不到构建脚本：${script}`);
  }
  await run(script, [], repoRoot, { ...process.env, PYTHONPATH: pyDir });
}

/**
 * 把一张 DXF/DWG 摊平成 **可交互图元 JSON**（图元折线 + 文字，颜色/线型已算好）。
 * 通过 `python -m moz_cadview <图> --model-json <临时文件>` 实现——纯 Python + .so，
 * **不需要 PySide6**；扩展自带后端的打包布局就是 python/（见 scripts/bundle-backend.sh）。
 * `dark` 让后端按深色画布配色（7 号色翻白），配合 VS Code 深色主题的深灰背景。
 */
export async function dumpModel(
  pyDir: string,
  drawingPath: string,
  dark: boolean,
): Promise<string> {
  const interpreter = vscode.workspace
    .getConfiguration('mozDxfViewer')
    .get<string>('python', 'python3');
  const soFile = findLibSo(pyDir);
  const tmpJson = path.join(os.tmpdir(), `moz-model-${Date.now()}.json`);
  const args = ['-m', 'moz_cadview', drawingPath, '--model-json', tmpJson];
  if (dark) {
    args.push('--dark');
  }
  const env: NodeJS.ProcessEnv = { ...process.env };
  if (soFile) {
    env.MOZ_CADIO_LIB = soFile;
  }
  try {
    await run(interpreter, args, pyDir, env);
    return await fs.promises.readFile(tmpJson, 'utf-8');
  } finally {
    await fs.promises.rm(tmpJson, { force: true });
  }
}