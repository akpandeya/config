const http = require('http');
const execSync = require('child_process').execSync;
const WebSocket = require('/Users/dipukumari/.gemini/antigravity-cli/scratch/node_modules/ws');

// Find the Antigravity remote debugging port using lsof
function getDebugPort() {
  try {
    const output = execSync('lsof -i -P -n | grep "Antigravi" | grep -oE "127.0.0.1:[0-9]+" | head -n 1', { encoding: 'utf8' });
    const match = output.match(/:([0-9]+)/);
    if (match) return parseInt(match[1], 10);
  } catch (e) {
    // Ignore error
  }
  return null;
}

function getWebSocketUrl(port) {
  return new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/json/list`, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const list = JSON.parse(data);
          const page = list.find(t => t.type === 'page');
          if (page && page.webSocketDebuggerUrl) {
            resolve(page.webSocketDebuggerUrl);
          } else {
            reject('No inspectable page found');
          }
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

function evaluatePage(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.on('open', () => {
      const msg = {
        id: 1,
        method: 'Runtime.evaluate',
        params: {
          expression: `(() => {
            const reactRoot = document.querySelector('#root');
            if (!reactRoot) return null;
            const key = Object.keys(reactRoot).find(k => k.startsWith('__reactContainer') || k.startsWith('__reactFiber'));
            if (!key) return null;
            const fiber = reactRoot[key];
            
            let foundVal = null;
            function traverse(node) {
              if (!node || foundVal) return;
              if (node.memoizedState) {
                let state = node.memoizedState;
                while (state) {
                  if (state.memoizedState && typeof state.memoizedState === 'object') {
                    if (state.memoizedState.cascadeModelConfigData || state.memoizedState.clientModelConfigs) {
                      foundVal = state.memoizedState;
                      return;
                    }
                    if (state.memoizedState.userStatus && state.memoizedState.userStatus.cascadeModelConfigData) {
                      foundVal = state.memoizedState.userStatus;
                      return;
                    }
                  }
                  state = state.next;
                }
              }
              if (node.memoizedProps && typeof node.memoizedProps === 'object') {
                if (node.memoizedProps.userStatus && node.memoizedProps.userStatus.cascadeModelConfigData) {
                  foundVal = node.memoizedProps.userStatus;
                  return;
                }
              }
              traverse(node.child);
              traverse(node.sibling);
            }
            traverse(fiber);
            if (foundVal) {
              const data = foundVal.cascadeModelConfigData || foundVal;
              if (data && data.clientModelConfigs) {
                return JSON.stringify(data.clientModelConfigs.map(c => ({
                  label: c.label,
                  remainingFraction: c.quotaInfo?.remainingFraction,
                  resetTimeSeconds: c.quotaInfo?.resetTime?.seconds
                })), (k, v) => typeof v === 'bigint' ? v.toString() : v);
              }
            }
            return null;
          })()`
        }
      };
      ws.send(JSON.stringify(msg));
    });
    ws.on('message', (data) => {
      try {
        const resp = JSON.parse(data.toString());
        if (resp.result && resp.result.result && resp.result.result.value) {
          resolve(JSON.parse(resp.result.result.value));
        } else {
          resolve(null);
        }
      } catch (e) {
        reject(e);
      }
      ws.close();
    });
    ws.on('error', reject);
  });
}

async function main() {
  const modelLabel = process.argv[2];
  if (!modelLabel) {
    console.log(JSON.stringify({ error: 'No model label provided' }));
    process.exit(0);
  }

  const port = getDebugPort();
  if (!port) {
    console.log(JSON.stringify({ error: 'Antigravity app not running' }));
    process.exit(0);
  }

  try {
    const wsUrl = await getWebSocketUrl(port);
    const configs = await evaluatePage(wsUrl);
    if (!configs) {
      console.log(JSON.stringify({ error: 'Could not fetch model configs' }));
      process.exit(0);
    }

    const config = configs.find(c => c.label === modelLabel);
    if (!config) {
      console.log(JSON.stringify({ error: `Model not found: ${modelLabel}` }));
      process.exit(0);
    }

    const remainingPercent = Math.round((config.remainingFraction ?? 1.0) * 100);
    let resetsInStr = '';
    
    if (config.resetTimeSeconds) {
      const resetTimeMs = Number(config.resetTimeSeconds) * 1000;
      const diffMs = resetTimeMs - Date.now();
      if (diffMs > 0) {
        const diffMins = Math.ceil(diffMs / 60000);
        if (diffMins < 60) {
          resetsInStr = `refreshes in ${diffMins}m`;
        } else {
          const hours = Math.floor(diffMins / 60);
          const mins = diffMins % 60;
          resetsInStr = `refreshes in ${hours}h${mins > 0 ? mins + 'm' : ''}`;
        }
      } else {
        resetsInStr = 'refreshed';
      }
    }

    console.log(JSON.stringify({
      remaining: remainingPercent,
      resets_in: resetsInStr
    }));
  } catch (e) {
    console.log(JSON.stringify({ error: e.message }));
  }
}

main();
