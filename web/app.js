const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));

const api = async (path, options) => {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `${response.status}`);
  return data;
};

const titleMap = {
  command: 'Command Center', runs: 'Run Ledger', plans: 'Plan History',
  capabilities: 'Capability Registry', learning: 'Learning Intelligence',
  evidence: 'Evidence Ledger', verifier: 'Verifier Center', policies: 'Policy Gates',
  runtime: 'Runtime Health', fleet: 'Executor Fleet', settings: 'Governance Settings'
};

function kv(label, value, cls = '') {
  return `<div class="data-row"><span>${esc(label)}</span><b class="${cls}">${esc(value)}</b></div>`;
}

async function loadHealth() {
  try {
    const data = await api('/api/health');
    $('#health').textContent = data.status === 'ok' ? 'RUNTIME HEALTHY' : 'RUNTIME DEGRADED';
    $('#capCount').textContent = data.capabilities;
  } catch {
    $('#health').textContent = 'RUNTIME UNKNOWN';
  }
}

async function loadRuntimeSummary() {
  try {
    const [runtime, executor, fleet] = await Promise.all([
      api('/api/runtime'), api('/api/executor'), api('/api/fleet')
    ]);
    const sandbox = runtime.sandbox;
    const rows = [
      ['GitHub connector', runtime.connectors.includes('github') ? 'AVAILABLE' : 'UNAVAILABLE', runtime.connectors.includes('github') ? 'ok' : 'warn'],
      ['Remote executor', executor.status, executor.status === 'AVAILABLE' ? 'ok' : 'warn'],
      ['Executor fleet', fleet.status, fleet.status === 'AVAILABLE' ? 'ok' : 'warn'],
      ['Fleet backend', fleet.backend || 'UNCONFIGURED', fleet.backend ? 'ok' : 'warn'],
      ['Fleet evidence chain', fleet.event_chain || 'UNAVAILABLE', fleet.event_chain === 'VERIFIED' ? 'ok' : 'warn'],
      ['Isolated runner (local)', sandbox.status, sandbox.status === 'AVAILABLE' ? 'ok' : 'warn'],
      ['Network default', runtime.network_default, runtime.network_default === 'DENY' ? 'ok' : 'warn'],
      ['State persistence', runtime.state_persistence, runtime.state_persistence.includes('PERSISTENT') ? 'ok' : 'warn'],
      ['Production mutation', runtime.production_mutation, 'warn']
    ];
    $('#runtimeSummary').innerHTML = rows.map(([label, value, cls]) =>
      `<div><span>${esc(label)}</span><b class="${cls}">${esc(value)}</b></div>`
    ).join('');
  } catch {
    $('#runtimeSummary').innerHTML = '<div><span>Runtime status</span><b class="warn">UNKNOWN</b></div>';
  }
}

function render(plan) {
  $('#planStatus').textContent = plan.status;
  $('#planStatus').className = `badge ${plan.status === 'VERIFIED_PLAN' ? 'verified' : 'blocked'}`;
  $('#selectedCount').textContent = plan.selections.length;
  $('#stageCount').textContent = plan.stages.length;
  $('#blockerCount').textContent = plan.blockers.length;
  $('#dag').className = 'dag';
  $('#dag').innerHTML = plan.stages.map((stage, index) =>
    `<div class="stage"><span class="stage-index">S${index + 1}</span>${stage.map((id) =>
      `<div class="node-card"><b>${esc(id)}</b><small>${index === plan.stages.length - 1 ? 'verification / evidence' : 'governed worker'}</small></div>`
    ).join('')}</div>`
  ).join('');
  $('#gates').innerHTML = plan.authority_gates.map((gate) =>
    `<div class="gate"><b>${esc(gate.capability_id)}</b><em class="${gate.decision === 'ALLOW' ? 'allow' : gate.decision === 'APPROVAL_REQUIRED' ? 'approval' : 'block'}">${esc(gate.decision)}</em><small>${esc(gate.authority)} · ${esc(gate.reason)}</small></div>`
  ).join('') || '<div class="muted">No gates.</div>';
  const events = [
    ['Intent compiled', plan.intents.join(', ')],
    ['Capabilities routed', `${plan.selections.length} workers + ${plan.io_capabilities.length} I/O bindings`],
    ['DAG composed', `${plan.stages.length} execution stages`],
    ['Policy evaluated', `${plan.authority_gates.length} authority decisions`],
    ['Independent plan verification', plan.status],
    ['Durable plan record', plan.durable_record || 'UNAVAILABLE']
  ];
  $('#timeline').innerHTML = events.map(([label, value]) =>
    `<div class="timeline-row"><span class="node"></span><div><b>${esc(label)}</b><small>${esc(value)}</small></div></div>`
  ).join('');
}

async function compilePlan() {
  const button = $('#planBtn');
  button.disabled = true;
  button.textContent = 'COMPILING…';
  try {
    const data = await api('/api/plan', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({goal: $('#goal').value, mode: $('#mode').value})
    });
    render(data);
  } catch (error) {
    $('#planStatus').textContent = 'BLOCKED';
    $('#planStatus').className = 'badge blocked';
    $('#gates').innerHTML = `<div class="gate"><b>Planner error</b><em class="block">BLOCK</em><small>${esc(error.message)}</small></div>`;
  } finally {
    button.disabled = false;
    button.textContent = 'COMPILE PLAN';
  }
}

async function loadRuns(target = '#runsContent') {
  const rows = await api('/api/runs');
  $(target).innerHTML = rows.length ? rows.map((run) =>
    `<article class="record"><div><b>${esc(run.run_id)}</b><small>${esc(run.timestamp)}</small></div><span class="badge ${run.metadata?.plan_status === 'VERIFIED_PLAN' ? 'verified' : 'unknown'}">${esc(run.metadata?.plan_status || run.status)}</span><p>${esc(run.metadata?.goal || 'No goal captured')}</p><small>${esc(run.metadata?.mode || '—')} · ${esc(run.plan_id)}</small></article>`
  ).join('') : '<div class="empty-state">No runs yet. Compile a plan first.</div>';
}

async function loadCapabilities() {
  const rows = await api('/api/capabilities');
  $('#capabilitiesContent').innerHTML = rows.map((capability) =>
    `<article class="cap-card"><div class="cap-top"><b>${esc(capability.id)}</b><span>${esc(capability.kind)}</span></div><p>${esc(capability.description)}</p><div class="chips"><i>${esc(capability.authority)}</i>${capability.requires_tools.map((x) => `<i>${esc(x)}</i>`).join('')}${capability.requires_connectors.map((x) => `<i>${esc(x)}</i>`).join('')}</div><small>risk ${Number(capability.risk).toFixed(2)} · confidence ${Number(capability.confidence).toFixed(2)}</small></article>`
  ).join('');
}

async function loadLearning() {
  const data = await api('/api/learning');
  const entries = Object.entries(data);
  $('#learningContent').innerHTML = entries.length ? entries.map(([id, stats]) =>
    `<article class="record"><div><b>${esc(id)}</b><small>${stats.samples} samples</small></div><span class="signal">${Number(stats.routing_signal).toFixed(3)}</span><p>success ${Number(stats.success_rate).toFixed(2)} · unique value ${Number(stats.unique_value).toFixed(2)} · false positive ${Number(stats.false_positive_rate).toFixed(2)}</p></article>`
  ).join('') : '<div class="empty-state">No feedback samples yet. Learning starts neutral and cannot override authority gates.</div>';
}

async function loadEvidence() {
  const data = await api('/api/evidence');
  $('#evidenceIntegrity').textContent = data.integrity;
  $('#evidenceIntegrity').className = `badge ${data.integrity === 'VERIFIED' ? 'verified' : 'blocked'}`;
  $('#evidenceContent').innerHTML = data.events.length ? data.events.map((event) =>
    `<div class="timeline-row"><span class="node"></span><div><b>${esc(event.kind)} · ${esc(event.subject)}</b><small>${esc(event.timestamp)} · #${event.seq}</small><code>${esc(event.event_hash.slice(0, 20))}…</code></div></div>`
  ).join('') : '<div class="empty-state">No runtime evidence yet.</div>';
}

async function loadVerifier() {
  const [data, fleet] = await Promise.all([api('/api/verifier'), api('/api/fleet')]);
  const counts = fleet.stats?.counts || {};
  $('#verifierContent').innerHTML =
    kv('Independent verifier', data.independent_verifier, 'ok') +
    kv('Receipt equals verification', String(data.receipt_is_verification), data.receipt_is_verification ? 'warn' : 'ok') +
    kv('Fleet verifier identity', data.fleet_verifier || 'SEPARATE_IDENTITY_REQUIRED', 'ok') +
    kv('Fleet backend', fleet.backend || 'UNCONFIGURED', fleet.backend ? 'ok' : 'warn') +
    kv('Executed awaiting verification', counts.EXECUTED ?? 0, counts.EXECUTED ? 'warn' : 'ok') +
    kv('Currently verifying', counts.VERIFYING ?? 0, counts.VERIFYING ? 'warn' : '') +
    kv('Fleet verified', counts.VERIFIED ?? 0, 'ok') +
    kv('Fleet failed', counts.FAILED ?? 0, counts.FAILED ? 'warn' : '') +
    kv('Fleet blocked', counts.BLOCKED ?? 0, counts.BLOCKED ? 'warn' : '') +
    kv('Verified plans', data.verified_plans, 'ok') +
    kv('Blocked plans', data.blocked_plans, data.blocked_plans ? 'warn' : '') +
    (data.last_plan ? `<article class="record wide"><b>Latest plan</b><p>${esc(data.last_plan.metadata?.goal || '—')}</p><small>${esc(data.last_plan.metadata?.plan_status || 'UNKNOWN')}</small></article>` : '');
}

async function loadPolicies() {
  const data = await api('/api/policies');
  const executor = data.remote_executor || {};
  const fleet = data.fleet || {};
  $('#policiesContent').innerHTML =
    `<div class="invariant-grid">${data.invariants.map((x) => `<div class="invariant">${esc(x)}</div>`).join('')}</div>` +
    `<h3>Authority matrix</h3><div class="data-grid">${Object.entries(data.authority).map(([key, value]) => kv(key, value, key === 'READ' || key === 'COMPUTE' ? 'ok' : 'warn')).join('')}</div>` +
    `<h3>Network</h3><div class="data-grid">${kv('Default', data.network.default, 'ok')}${kv('Selective egress', data.network.selective_egress, 'warn')}</div>` +
    `<h3>Remote executor</h3><div class="data-grid">${kv('Protocol', executor.protocol || 'executor-v1', 'ok')}${kv('Transport', executor.transport || 'HTTPS REQUIRED', 'ok')}${kv('Operation classes', (executor.operation_classes || ['COMPUTE']).join(', '), 'ok')}${kv('Receipt equals verification', String(Boolean(executor.receipt_is_verification)), executor.receipt_is_verification ? 'warn' : 'ok')}</div>` +
    `<h3>Executor fleet</h3><div class="data-grid">${kv('Lease model', fleet.lease_model || 'ATOMIC_EXCLUSIVE_TTL', 'ok')}${kv('Worker database secret', fleet.worker_db_secret || 'NEVER_EXPOSED', 'ok')}${kv('Verification', fleet.verification || 'SEPARATE_LEASE_AND_IDENTITY', 'ok')}</div>`;
}

async function loadRuntime() {
  const [runtime, executor, fleet] = await Promise.all([api('/api/runtime'), api('/api/executor'), api('/api/fleet')]);
  const remote = executor.remote || {};
  const counts = fleet.stats?.counts || {};
  $('#runtimeContent').innerHTML =
    kv('Tools', runtime.tools.join(', ')) +
    kv('Connectors', runtime.connectors.join(', ')) +
    kv('Standing grants', runtime.standing_grants.join(', ') || 'NONE', 'ok') +
    kv('Network default', runtime.network_default, 'ok') +
    kv('Remote executor', executor.status, executor.status === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Remote execution', executor.execution, executor.execution === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Executor protocol', remote.protocol || 'executor-v1') +
    kv('Receipt verification', 'PENDING / SEPARATE', 'warn') +
    kv('Fleet', fleet.status, fleet.status === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Fleet backend', fleet.backend || 'UNCONFIGURED', fleet.backend ? 'ok' : 'warn') +
    kv('Fleet event chain', fleet.event_chain || 'UNAVAILABLE', fleet.event_chain === 'VERIFIED' ? 'ok' : 'warn') +
    kv('Queued jobs', counts.QUEUED ?? 0, counts.QUEUED ? 'warn' : '') +
    kv('Active execution leases', counts.LEASED ?? 0, counts.LEASED ? 'warn' : '') +
    kv('Awaiting verification', counts.EXECUTED ?? 0, counts.EXECUTED ? 'warn' : '') +
    kv('Sandbox (local)', runtime.sandbox.status, runtime.sandbox.status === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Sandbox backend', runtime.sandbox.backend || 'NOT PRESENT') +
    kv('Egress allowlist', runtime.sandbox.egress_allowlist, 'warn') +
    kv('State persistence', runtime.state_persistence, runtime.state_persistence.includes('PERSISTENT') ? 'ok' : 'warn') +
    kv('Production mutation', runtime.production_mutation, 'warn') +
    (executor.reason ? `<article class="record wide"><b>Executor status reason</b><p>${esc(executor.reason)}</p></article>` : '') +
    (fleet.reason ? `<article class="record wide"><b>Fleet status reason</b><p>${esc(fleet.reason)}</p></article>` : '');
}

async function loadFleet() {
  const data = await api('/api/fleet');
  const counts = data.stats?.counts || {};
  const head = data.stats?.event_head || 'NONE';
  $('#fleetContent').innerHTML =
    kv('Fleet status', data.status, data.status === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Execution', data.execution, data.execution === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Durable backend', data.backend || 'UNCONFIGURED', data.backend ? 'ok' : 'warn') +
    kv('Event chain', data.event_chain || 'UNAVAILABLE', data.event_chain === 'VERIFIED' ? 'ok' : 'warn') +
    kv('Event head', head) +
    kv('Queued', counts.QUEUED ?? 0, counts.QUEUED ? 'warn' : '') +
    kv('Leased / running', counts.LEASED ?? 0, counts.LEASED ? 'warn' : '') +
    kv('Executed / awaiting verifier', counts.EXECUTED ?? 0, counts.EXECUTED ? 'warn' : '') +
    kv('Verification leases', counts.VERIFYING ?? 0, counts.VERIFYING ? 'warn' : '') +
    kv('Verified', counts.VERIFIED ?? 0, 'ok') +
    kv('Failed', counts.FAILED ?? 0, counts.FAILED ? 'warn' : '') +
    kv('Blocked', counts.BLOCKED ?? 0, counts.BLOCKED ? 'warn' : '') +
    kv('Worker auth', data.worker_auth_configured ? 'CONFIGURED' : 'UNCONFIGURED', data.worker_auth_configured ? 'ok' : 'warn') +
    kv('Verifier auth', data.verifier_auth_configured ? 'CONFIGURED' : 'UNCONFIGURED', data.verifier_auth_configured ? 'ok' : 'warn') +
    kv('DB secret exposed to workers', String(Boolean(data.database_secret_exposed_to_workers)), data.database_secret_exposed_to_workers ? 'warn' : 'ok') +
    `<article class="record wide"><b>Delivery semantics</b><p>One active lease per job. Lease expiry enables retry, so delivery is retry-capable at-least-once — not falsely claimed as mathematical exactly-once. Independent verification is a separate lease and identity.</p></article>` +
    (data.reason ? `<article class="record wide"><b>Fleet blocker</b><p>${esc(data.reason)}</p></article>` : '');
}

async function loadSettings() {
  const [health, runtime, executor, fleet] = await Promise.all([
    api('/api/health'), api('/api/runtime'), api('/api/executor'), api('/api/fleet')
  ]);
  $('#settingsContent').innerHTML =
    kv('Version', health.version) +
    kv('Trust model', health.trust_model, 'ok') +
    kv('Default orchestration mode', 'ALL') +
    kv('Network policy', runtime.network_default, 'ok') +
    kv('Remote executor', executor.status, executor.status === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Remote operation class', 'COMPUTE', 'ok') +
    kv('Executor fleet', fleet.status, fleet.status === 'AVAILABLE' ? 'ok' : 'warn') +
    kv('Fleet backend', fleet.backend || 'UNCONFIGURED', fleet.backend ? 'ok' : 'warn') +
    kv('Production writes', runtime.production_mutation, 'warn') +
    kv('State model', runtime.state_persistence, runtime.state_persistence.includes('PERSISTENT') ? 'ok' : 'warn') +
    `<article class="record wide"><b>Governance note</b><p>Runtime truth is visible here, but execution authority is intentionally not exposed as an unauthenticated browser control. Fleet workers use a dedicated worker bearer and executor transport secret; verifier workers use a different verifier bearer; database service-role credentials remain server-side.</p></article>`;
}

const loaders = {
  runs: () => loadRuns('#runsContent'),
  plans: () => loadRuns('#plansContent'),
  capabilities: loadCapabilities,
  learning: loadLearning,
  evidence: loadEvidence,
  verifier: loadVerifier,
  policies: loadPolicies,
  runtime: loadRuntime,
  fleet: loadFleet,
  settings: loadSettings
};

async function showView(name) {
  $$('.view').forEach((view) => view.classList.toggle('active', view.id === `view-${name}`));
  $$('#nav button').forEach((button) => button.classList.toggle('active', button.dataset.view === name));
  $('#pageTitle').textContent = titleMap[name] || name;
  if (loaders[name]) {
    try {
      await loaders[name]();
    } catch (error) {
      const target = $(`#view-${name} .page-card`);
      if (target) target.insertAdjacentHTML('beforeend', `<div class="error-box">${esc(error.message)}</div>`);
    }
  }
}

$('#nav').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-view]');
  if (button) showView(button.dataset.view);
});
$('#planBtn').addEventListener('click', compilePlan);
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-refresh]');
  if (button && loaders[button.dataset.refresh]) loaders[button.dataset.refresh]();
});

loadHealth();
loadRuntimeSummary();
