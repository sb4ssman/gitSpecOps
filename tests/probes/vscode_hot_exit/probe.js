const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

function files(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
    const file = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) return [];
    return entry.isDirectory() ? files(file) : [file];
  });
}

exports.run = async function () {
  const root = path.dirname(__dirname);
  const file = path.join(root, 'workspace', 'probe.txt');
  const original = fs.readFileSync(file);
  const marker = Buffer.from('synthetic-unsaved-recovery-probe');
  const result = {version: vscode.version, passed: false};
  try {
    const document = await vscode.workspace.openTextDocument(file);
    const editor = await vscode.window.showTextDocument(document);
    const settings = vscode.workspace.getConfiguration('files', document.uri);
    result.autoSave = settings.get('autoSave');
    result.hotExit = settings.get('hotExit');
    const start = Date.now();
    const edited = await editor.edit(builder =>
      builder.insert(new vscode.Position(0, 0), marker.toString() + '\n'));
    result.backupBeforeExit = false;
    result.elapsedMs = null;
    for (let attempt = 0; attempt < 40; ++attempt) {
      await new Promise(resolve => setTimeout(resolve, 500));
      result.backupBeforeExit = files(path.join(root, 'profile', 'Backups')).some(backup => {
        try { return fs.readFileSync(backup).includes(marker); }
        catch (error) {
          if (error.code === 'ENOENT') return false; // backup replacement raced this read
          throw error;
        }
      });
      if (result.backupBeforeExit) {
        result.elapsedMs = Date.now() - start;
        break;
      }
    }
    result.dirty = document.isDirty;
    result.savedFileUnchanged = fs.readFileSync(file).equals(original);
    result.passed = edited && result.backupBeforeExit && result.dirty
      && result.savedFileUnchanged && result.autoSave === 'off';
  } catch (error) {
    result.error = 'Test harness failed; inspect the local logs for details.';
    console.error(error);
  }
  const temporary = path.join(root, 'result.json.tmp');
  fs.writeFileSync(temporary, JSON.stringify(result, null, 2));
  fs.renameSync(temporary, path.join(root, 'result.json'));
  if (!result.passed) throw new Error('Backup pre-exit experiment did not pass');
};
