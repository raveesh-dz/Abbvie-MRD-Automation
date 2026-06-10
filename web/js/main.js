import { loadTables, wireSimulate, refreshDemoChip } from './data.js';
import { wirePipeline } from './pipeline.js';
import { loadViews, wireRunSelected } from './views.js';
import { wireEngine, loadEngineItems } from './engine.js';
import { toast } from './ui.js';

export async function refreshAll() {
  // independent fetches — run them concurrently
  await Promise.all([loadTables(), loadViews(), refreshDemoChip()]);
}

wireSimulate(refreshAll);
wirePipeline(refreshAll);
wireRunSelected(refreshAll);
wireEngine();
// boot fetches must fail loudly — otherwise the skeletons freeze silently
refreshAll().catch((e) => toast(e.message, 'fail'));
loadEngineItems().catch((e) => toast(e.message, 'fail'));
