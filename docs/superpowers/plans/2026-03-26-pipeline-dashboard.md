# Pipeline Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the linear 4-step clip wizard with a modular pipeline dashboard where dubbing and splitscreen are independently togglable stages.

**Architecture:** All changes are in `app/static/index.html` — a single-file vanilla JS/HTML/CSS dashboard. Steps 1-2 stay the same. Step 3 becomes a pipeline options panel with DUB and SPLITSCREEN stage cards. Step 4 becomes a grouped results view that handles both job types. No backend changes needed.

**Tech Stack:** Vanilla HTML/CSS/JS, Tailwind CDN, existing REST API endpoints.

**Spec:** `docs/superpowers/specs/2026-03-26-pipeline-dashboard-design.md`

---

## File Structure

- **Modify:** `app/static/index.html` — the entire dashboard (~2260 lines)
- **Modify:** `app/schemas/dubbing.py` — add `source_url` to `DubbingJobSummaryResponse` (needed for Library tab filter)
- **Modify:** `app/routes/dubbing.py` — pass `source_url` in list response

Changes to index.html organized by section:
1. CSS additions (new styles for stage cards, language picker, pipeline progress)
2. HTML changes to step 3 and step 4
3. JS additions for dubbing API calls, pipeline state management, and polling
4. JS modifications to existing generate flow

---

### Task 1: Add CSS for pipeline stage cards and language picker

**Files:**
- Modify: `app/static/index.html:8-508` (CSS section)

- [ ] **Step 1: Add stage card styles**

Add after the `.actions` rule (around line 149) in the `<style>` block:

```css
/* Pipeline stage cards */
.stage-card {
  background: #141414; border: 1px solid #1a1a1a; border-radius: 6px;
  margin-bottom: 16px; overflow: hidden;
}
.stage-card.enabled { border-color: #2a2a2a; }
.stage-header {
  display: flex; align-items: center; gap: 12px; padding: 16px 20px;
  cursor: pointer; user-select: none;
}
.stage-toggle {
  width: 40px; height: 22px; border-radius: 11px; background: #2a2a2a;
  position: relative; transition: background 0.2s; flex-shrink: 0; border: none; cursor: pointer;
}
.stage-toggle.on { background: #ff3a2f; }
.stage-toggle::after {
  content: ''; position: absolute; top: 3px; left: 3px;
  width: 16px; height: 16px; border-radius: 50%; background: #fff;
  transition: left 0.2s;
}
.stage-toggle.on::after { left: 21px; }
.stage-name {
  font-size: 13px; font-weight: 700; letter-spacing: 2px; color: #888;
  flex: 1;
}
.stage-card.enabled .stage-name { color: #fff; }
.stage-body {
  display: none; padding: 0 20px 20px;
}
.stage-card.enabled .stage-body { display: block; }

/* Language picker */
.lang-picker { display: flex; gap: 10px; margin-bottom: 16px; }
.lang-btn {
  background: #0a0a0a; border: 1px solid #2a2a2a; color: #888;
  padding: 10px 20px; font-family: inherit; font-size: 12px; font-weight: 700;
  letter-spacing: 1px; cursor: pointer; border-radius: 4px; transition: all 0.2s;
}
.lang-btn:hover { border-color: #555; }
.lang-btn.selected { border-color: #ff3a2f; color: #ff3a2f; background: rgba(255,58,47,0.08); }

/* Credit summary */
.credit-summary {
  background: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 4px;
  padding: 16px 20px; margin-top: 20px; font-size: 13px;
}
.credit-line { display: flex; justify-content: space-between; color: #666; margin-bottom: 6px; }
.credit-total { display: flex; justify-content: space-between; color: #fff; font-weight: 700; border-top: 1px solid #1a1a1a; padding-top: 8px; margin-top: 8px; }
.credit-warning { color: #ef4444; font-size: 12px; margin-top: 8px; }

/* Dubbed audio toggle */
.dubbed-audio-toggle {
  display: flex; align-items: center; gap: 12px; padding: 12px 0;
  margin-bottom: 16px; font-size: 13px; color: #888;
}

/* Pipeline results */
.pipeline-results { display: flex; flex-direction: column; gap: 20px; }
.result-clip-group {
  background: #141414; border: 1px solid #1a1a1a; border-radius: 6px; overflow: hidden;
}
.result-clip-header {
  padding: 14px 20px; font-size: 14px; font-weight: 700; color: #ccc;
  border-bottom: 1px solid #1a1a1a;
}
.result-stage-label {
  padding: 10px 20px 4px; font-size: 11px; color: #555; letter-spacing: 2px; font-weight: 700;
}
.result-row {
  padding: 10px 20px; display: flex; align-items: center; gap: 12px; font-size: 13px;
}
.result-row .label { flex: 1; color: #999; }
.result-row .status-text { color: #666; font-size: 12px; min-width: 90px; }
.result-actions { display: flex; gap: 6px; }
.result-actions button {
  background: #ff3a2f; color: #fff; border: none; padding: 5px 10px;
  border-radius: 3px; cursor: pointer; font-family: inherit; font-size: 11px;
}
.result-actions a {
  color: #666; font-size: 11px; text-decoration: none; border: 1px solid #333;
  padding: 5px 10px; border-radius: 3px;
}
```

- [ ] **Step 2: Verify styles render**

Open the dashboard in browser, confirm no CSS errors in console. The new classes won't be visible yet since no HTML uses them.

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add CSS for pipeline stage cards, language picker, and results"
```

---

### Task 2: Add source_url to dubbing list response (backend fix)

**Files:**
- Modify: `app/schemas/dubbing.py:50-55`
- Modify: `app/routes/dubbing.py:157-166`

The `GET /dubbing` list endpoint returns `DubbingJobSummaryResponse` which omits `source_url`. The Library tab needs this to match dubbing jobs to extraction clips.

- [ ] **Step 1: Add source_url to DubbingJobSummaryResponse**

In `app/schemas/dubbing.py`, add `source_url` to the summary schema:

```python
class DubbingJobSummaryResponse(BaseModel):
    id: str
    status: str
    source_url: str
    languages: list[str]
    credits_charged: int
    created_at: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Pass source_url in list route**

In `app/routes/dubbing.py`, update the list response to include `source_url`:

```python
DubbingJobSummaryResponse(
    id=str(j.id),
    status=j.status.value,
    source_url=j.source_url,
    languages=j.languages,
    credits_charged=j.credits_charged,
    created_at=j.created_at.isoformat(),
)
```

- [ ] **Step 3: Commit**

```bash
git add app/schemas/dubbing.py app/routes/dubbing.py
git commit -m "feat: add source_url to dubbing list response for Library tab filtering"
```

---

### Task 3: Replace step 3 HTML with pipeline options

**Files:**
- Modify: `app/static/index.html:573-642` (Step 3 HTML)

- [ ] **Step 1: Replace step 3 HTML**

Replace the entire step 3 div (lines 573-642) with:

```html
<!-- Step 3: Pipeline Options -->
<div class="step" id="step3">
  <div class="step-title">STEP 3</div>
  <h2>Build your pipeline</h2>
  <p style="color:#666; font-size:13px; margin-bottom:20px;">Choose what to do with your selected clips. Enable one or both stages.</p>

  <!-- DUB Stage -->
  <div class="stage-card" id="dubStage">
    <div class="stage-header" onclick="toggleStage('dub')">
      <button class="stage-toggle" id="dubToggle"></button>
      <div class="stage-name">DUB</div>
      <div style="font-size:11px;color:#555;">ElevenLabs + Sync Labs lip-sync</div>
    </div>
    <div class="stage-body">
      <div style="font-size:12px;color:#666;margin-bottom:12px;">Select target languages (1 credit per language per clip)</div>
      <div class="lang-picker" id="langPicker">
        <button class="lang-btn" data-lang="es" onclick="toggleLang(this)">ES <span style="color:#555">Spanish</span></button>
        <button class="lang-btn" data-lang="fr" onclick="toggleLang(this)">FR <span style="color:#555">French</span></button>
        <button class="lang-btn" data-lang="he" onclick="toggleLang(this)">HE <span style="color:#555">Hebrew</span></button>
      </div>
    </div>
  </div>

  <!-- SPLITSCREEN Stage -->
  <div class="stage-card" id="splitscreenStage">
    <div class="stage-header" onclick="toggleStage('splitscreen')">
      <button class="stage-toggle" id="splitscreenToggle"></button>
      <div class="stage-name">SPLITSCREEN</div>
      <div style="font-size:11px;color:#555;">Gameplay footage + captions</div>
    </div>
    <div class="stage-body">
      <div class="gameplay-grid" id="gameplayGrid"></div>

      <div class="caption-layout">
        <div class="caption-preview-phone" id="captionPhone">
          <div class="phone-notch"></div>
          <div class="phone-source">
            <div class="phone-caption" id="captionPreviewText">
              <span class="phone-caption-word">NEVER</span>
              <span class="phone-caption-word">GIVE</span>
              <span class="phone-caption-word" style="color:#00FFFF">UP</span>
            </div>
          </div>
          <div class="phone-gameplay"></div>
        </div>
        <div class="caption-settings">
          <h3>CAPTION STYLE</h3>
          <div class="settings-grid">
            <div class="setting-group">
              <label>FONT</label>
              <select id="captionFont" onchange="updateCaptionPreview()">
                <option value="bangers" selected>Bangers</option>
                <option value="anton">Anton</option>
                <option value="bebas">Bebas Neue</option>
                <option value="poppins">Poppins</option>
                <option value="impact">Impact</option>
              </select>
            </div>
            <div class="setting-group">
              <label>FONT SIZE</label>
              <input type="number" id="captionSize" value="130" min="40" max="200" step="10" oninput="updateCaptionPreview()">
            </div>
            <div class="setting-group">
              <label>WORDS PER LINE</label>
              <input type="number" id="captionWords" value="3" min="1" max="6" oninput="updateCaptionPreview()">
            </div>
            <div class="setting-group">
              <label>POSITION</label>
              <select id="captionPosition" onchange="updateCaptionPreview()">
                <option value="top">Top</option>
                <option value="center" selected>Center</option>
                <option value="bottom">Bottom</option>
              </select>
            </div>
            <div class="setting-group">
              <label>TEXT COLOR</label>
              <div class="color-row">
                <div class="color-preview" id="primaryPreview" style="background:#FFFFFF;"></div>
                <input type="text" id="captionColor" value="FFFFFF" maxlength="6" oninput="updateColorPreview('primaryPreview', this.value); updateCaptionPreview()">
              </div>
            </div>
            <div class="setting-group">
              <label>OUTLINE COLOR</label>
              <div class="color-row">
                <div class="color-preview" id="outlinePreview" style="background:#000000;"></div>
                <input type="text" id="captionOutline" value="000000" maxlength="6" oninput="updateColorPreview('outlinePreview', this.value); updateCaptionPreview()">
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Dubbed audio for splitscreen toggle (only visible when both enabled) -->
  <div class="dubbed-audio-toggle" id="dubbedAudioRow" style="display:none;">
    <button class="stage-toggle on" id="dubbedAudioToggle" onclick="toggleDubbedAudio()"></button>
    <span>Use dubbed audio for splitscreen videos</span>
  </div>

  <!-- Credit summary -->
  <div class="credit-summary" id="creditSummary"></div>

  <div class="actions" style="margin-top:24px;">
    <button class="btn" id="pipelineGenerateBtn" onclick="runPipeline()" disabled>GENERATE</button>
    <button class="btn btn-secondary" onclick="showStep(2)">BACK</button>
  </div>
</div>
```

- [ ] **Step 2: Update step 2 NEXT button text**

The step 2 button currently says "NEXT: PICK GAMEPLAY". Update it to say "NEXT: BUILD PIPELINE":

```html
<button class="btn" id="nextToGameplay" onclick="showStep3()" disabled>NEXT: BUILD PIPELINE</button>
```

- [ ] **Step 3: Guard updateGenerateBtn against missing element**

Since the old `generateBtn` no longer exists in step 3, update `updateGenerateBtn()` to guard against null:

```javascript
function updateGenerateBtn() {
  const btn = document.getElementById('generateBtn');
  if (btn) btn.disabled = selectedGameplay.size === 0;
}
```

- [ ] **Step 4: Verify the HTML renders**

Open dashboard, navigate to step 3 (extract a video, select clips, click NEXT). Should see two collapsed stage cards. Nothing will be functional yet.

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html
git commit -m "feat: replace step 3 with pipeline options HTML"
```

---

### Task 4: Replace step 4 HTML with pipeline results

**Files:**
- Modify: `app/static/index.html:644-652` (Step 4 HTML)

- [ ] **Step 1: Replace step 4 HTML**

Replace the entire step 4 div (lines 644-652) with:

```html
<!-- Step 4: Pipeline Results -->
<div class="step" id="step4">
  <div class="step-title">RESULTS</div>
  <h2>Your pipeline</h2>
  <div class="pipeline-results" id="pipelineResults"></div>
  <div class="actions" style="margin-top:24px;">
    <button class="btn" onclick="startOver()">START OVER</button>
  </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add app/static/index.html
git commit -m "feat: replace step 4 with pipeline results HTML"
```

---

### Task 5: Add pipeline state management and stage toggle JS

**Files:**
- Modify: `app/static/index.html:843-850` (JS globals section)

- [ ] **Step 1: Add pipeline state globals**

Add these variables after the existing globals (around line 850):

```javascript
// Pipeline state
let dubEnabled = false;
let splitscreenEnabled = false;
let selectedLanguages = new Set();
let useDubbedAudio = true;
let pipelineState = null; // { clips: { [clipId]: { dubbingJobId, splitscreenJobIds, clipData } } }
```

- [ ] **Step 2: Add stage toggle functions**

Add after the new globals:

```javascript
function toggleStage(stage) {
  if (stage === 'dub') {
    dubEnabled = !dubEnabled;
    document.getElementById('dubStage').classList.toggle('enabled', dubEnabled);
    document.getElementById('dubToggle').classList.toggle('on', dubEnabled);
  } else {
    splitscreenEnabled = !splitscreenEnabled;
    document.getElementById('splitscreenStage').classList.toggle('enabled', splitscreenEnabled);
    document.getElementById('splitscreenToggle').classList.toggle('on', splitscreenEnabled);
  }
  // Show dubbed audio toggle only when both stages are on
  document.getElementById('dubbedAudioRow').style.display =
    (dubEnabled && splitscreenEnabled) ? 'flex' : 'none';
  updateCreditSummary();
  updatePipelineBtn();
}

function toggleLang(btn) {
  const lang = btn.dataset.lang;
  if (selectedLanguages.has(lang)) {
    selectedLanguages.delete(lang);
    btn.classList.remove('selected');
  } else {
    selectedLanguages.add(lang);
    btn.classList.add('selected');
  }
  updateCreditSummary();
  updatePipelineBtn();
}

function toggleDubbedAudio() {
  useDubbedAudio = !useDubbedAudio;
  document.getElementById('dubbedAudioToggle').classList.toggle('on', useDubbedAudio);
}

function updatePipelineBtn() {
  const btn = document.getElementById('pipelineGenerateBtn');
  if (!btn) return;
  const dubValid = !dubEnabled || selectedLanguages.size > 0;
  const splitValid = !splitscreenEnabled || selectedGameplay.size > 0;
  const anyEnabled = dubEnabled || splitscreenEnabled;
  const creditOk = getPipelineCost() <= parseInt(document.getElementById('creditsCount').textContent || '0');
  btn.disabled = !(anyEnabled && dubValid && splitValid && creditOk);
}
```

- [ ] **Step 3: Add credit summary function**

```javascript
function getPipelineCost() {
  let cost = 0;
  const numClips = selectedClips.size;
  if (dubEnabled) cost += numClips * selectedLanguages.size;
  if (splitscreenEnabled) {
    if (dubEnabled && useDubbedAudio) {
      // Each dubbed language gets splitscreened with each gameplay
      cost += numClips * selectedLanguages.size * selectedGameplay.size;
    } else {
      cost += numClips * selectedGameplay.size;
    }
  }
  return cost;
}

function updateCreditSummary() {
  const el = document.getElementById('creditSummary');
  if (!el) return;
  const numClips = selectedClips.size;
  const credits = parseInt(document.getElementById('creditsCount').textContent || '0');
  let lines = [];

  if (dubEnabled && selectedLanguages.size > 0) {
    const dubCost = numClips * selectedLanguages.size;
    lines.push(`<div class="credit-line"><span>DUB: ${numClips} clip${numClips !== 1 ? 's' : ''} × ${selectedLanguages.size} language${selectedLanguages.size !== 1 ? 's' : ''}</span><span>${dubCost} credit${dubCost !== 1 ? 's' : ''}</span></div>`);
  }
  if (splitscreenEnabled && selectedGameplay.size > 0) {
    let splitSrc, splitCost;
    if (dubEnabled && useDubbedAudio && selectedLanguages.size > 0) {
      splitSrc = numClips * selectedLanguages.size;
      splitCost = splitSrc * selectedGameplay.size;
      lines.push(`<div class="credit-line"><span>SPLITSCREEN: ${splitSrc} dubbed clip${splitSrc !== 1 ? 's' : ''} × ${selectedGameplay.size} gameplay</span><span>${splitCost} credit${splitCost !== 1 ? 's' : ''}</span></div>`);
    } else {
      splitCost = numClips * selectedGameplay.size;
      lines.push(`<div class="credit-line"><span>SPLITSCREEN: ${numClips} clip${numClips !== 1 ? 's' : ''} × ${selectedGameplay.size} gameplay</span><span>${splitCost} credit${splitCost !== 1 ? 's' : ''}</span></div>`);
    }
  }

  const total = getPipelineCost();
  if (total > 0) {
    lines.push(`<div class="credit-total"><span>TOTAL</span><span>${total} credit${total !== 1 ? 's' : ''} (you have ${credits})</span></div>`);
    if (total > credits) {
      lines.push(`<div class="credit-warning">Insufficient credits. You need ${total - credits} more.</div>`);
    }
  } else {
    lines.push(`<div class="credit-line"><span>Enable a stage to see costs</span><span></span></div>`);
  }

  el.innerHTML = lines.join('');
}
```

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add pipeline state management, stage toggles, and credit summary"
```

---

### Task 6: Update showStep3 to load gameplay into new location

**Files:**
- Modify: `app/static/index.html` — the `showStep3()` function (around line 1154)

- [ ] **Step 1: Update showStep3 function**

Replace the existing `showStep3()` function with:

```javascript
async function showStep3() {
  showStep(3);
  // Reset pipeline state
  dubEnabled = false;
  splitscreenEnabled = false;
  selectedLanguages.clear();
  selectedGameplay.clear();
  useDubbedAudio = true;
  document.getElementById('dubStage').classList.remove('enabled');
  document.getElementById('splitscreenStage').classList.remove('enabled');
  document.getElementById('dubToggle').classList.remove('on');
  document.getElementById('splitscreenToggle').classList.remove('on');
  document.getElementById('dubbedAudioToggle').classList.add('on');
  document.getElementById('dubbedAudioRow').style.display = 'none';
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('selected'));

  // Load gameplay
  const resp = await api('/gameplay');
  gameplayList = await resp.json();
  const grid = document.getElementById('gameplayGrid');
  grid.innerHTML = gameplayList.map(g => `
    <div class="gameplay-card" data-id="${g.id}" onclick="toggleGameplay(this, '${g.id}')">
      <div class="name">${g.name}</div>
      <div style="font-size:11px;color:#666;margin-top:4px;">${(g.duration/60).toFixed(1)} min</div>
    </div>
  `).join('');

  updateCreditSummary();
  updatePipelineBtn();
  updateCaptionPreview();
}
```

- [ ] **Step 2: Update toggleGameplay to also update pipeline state**

Find `toggleGameplay` and add `updatePipelineBtn()` and `updateCreditSummary()` calls:

```javascript
function toggleGameplay(el, id) {
  if (selectedGameplay.has(id)) {
    selectedGameplay.delete(id);
    el.classList.remove('selected');
  } else {
    selectedGameplay.add(id);
    el.classList.add('selected');
  }
  updateGenerateBtn();
  updateCreditSummary();
  updatePipelineBtn();
}
```

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html
git commit -m "feat: wire showStep3 to pipeline options and reset state"
```

---

### Task 7: Implement runPipeline — the main generate function

**Files:**
- Modify: `app/static/index.html` — replace `generateVideos()` usage

- [ ] **Step 1: Add the runPipeline function**

Add this function (replaces the old `generateVideos` for the CLIPS tab flow):

```javascript
async function runPipeline() {
  const btn = document.getElementById('pipelineGenerateBtn');
  btn.disabled = true;
  btn.textContent = 'GENERATING...';

  const captionStyle = getCaptionStyle();
  const gameplayIds = [...selectedGameplay];
  const languages = [...selectedLanguages];

  // Build pipeline state — keyed by clip storage_key
  pipelineState = { clips: {} };

  // We need clip data (preview_url) from the current extraction
  const clipDataMap = {};
  if (currentExtraction && currentExtraction.clips) {
    currentExtraction.clips.forEach(c => {
      if (selectedClips.has(c.storage_key)) {
        clipDataMap[c.storage_key] = c;
      }
    });
  }

  for (const clipKey of selectedClips) {
    const clip = clipDataMap[clipKey];
    const entry = {
      clipData: clip,
      dubbingJobId: null,
      dubbingOutputs: [],
      splitscreenJobIds: [],
    };

    // Submit dubbing if enabled
    if (dubEnabled && languages.length > 0 && clip) {
      try {
        const resp = await api('/dubbing', {
          method: 'POST',
          body: JSON.stringify({ source_url: clip.preview_url, languages })
        });
        if (resp.ok) {
          const data = await resp.json();
          entry.dubbingJobId = data.id;
        }
      } catch(e) { console.error('Dubbing submit failed', e); }
    }

    // Submit splitscreen if enabled and NOT waiting for dubbed audio
    if (splitscreenEnabled && gameplayIds.length > 0 && !(dubEnabled && useDubbedAudio)) {
      try {
        const resp = await api('/jobs/batch', {
          method: 'POST',
          body: JSON.stringify({ source_video_key: clipKey, gameplay_ids: gameplayIds, caption_style: captionStyle })
        });
        if (resp.ok) {
          const data = await resp.json();
          entry.splitscreenJobIds = data.jobs.map(j => j.id);
        }
      } catch(e) { console.error('Splitscreen submit failed', e); }
    }

    pipelineState.clips[clipKey] = entry;
  }

  showStep(4);
  btn.disabled = false;
  btn.textContent = 'GENERATE';
  loadCredits();

  // Start polling
  pollPipeline();
}
```

- [ ] **Step 2: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add runPipeline function for submitting dubbing and splitscreen jobs"
```

---

### Task 8: Implement pipeline polling and results rendering

**Files:**
- Modify: `app/static/index.html` — add polling + rendering functions

- [ ] **Step 1: Add pollPipeline function**

```javascript
async function pollPipeline() {
  if (!pipelineState) return;

  const captionStyle = getCaptionStyle();
  const gameplayIds = [...selectedGameplay];
  let anyActive = false;

  for (const [clipKey, entry] of Object.entries(pipelineState.clips)) {
    // Poll dubbing job
    if (entry.dubbingJobId) {
      try {
        const resp = await api(`/dubbing/${entry.dubbingJobId}`);
        if (resp.ok) {
          const job = await resp.json();
          entry.dubbingOutputs = job.outputs || [];

          // If using dubbed audio for splitscreen, submit splitscreen for completed outputs
          if (splitscreenEnabled && useDubbedAudio && dubEnabled && gameplayIds.length > 0) {
            for (const output of entry.dubbingOutputs) {
              if (output.status === 'completed' && output.output_video_key) {
                // Check if we already submitted splitscreen for this output
                const ssKey = `dub_${output.id}`;
                if (!entry._submittedSplitscreen) entry._submittedSplitscreen = new Set();
                if (!entry._submittedSplitscreen.has(ssKey)) {
                  entry._submittedSplitscreen.add(ssKey);
                  try {
                    const ssResp = await api('/jobs/batch', {
                      method: 'POST',
                      body: JSON.stringify({
                        source_video_key: output.output_video_key,
                        gameplay_ids: gameplayIds,
                        caption_style: captionStyle,
                      })
                    });
                    if (ssResp.ok) {
                      const ssData = await ssResp.json();
                      // Tag these jobs with the language they came from
                      ssData.jobs.forEach(j => {
                        entry.splitscreenJobIds.push({ id: j.id, lang: output.language });
                      });
                    }
                  } catch(e) { console.error('Splitscreen from dub failed', e); }
                }
              }
            }
          }

          // Check if dubbing is still active
          const dubTerminal = entry.dubbingOutputs.every(o =>
            o.status === 'completed' || o.status === 'failed'
          );
          if (!dubTerminal) anyActive = true;
        }
      } catch(e) {}
    }

    // Poll splitscreen jobs
    const ssJobs = entry.splitscreenJobIds;
    if (ssJobs.length > 0) {
      for (let i = 0; i < ssJobs.length; i++) {
        const jobRef = typeof ssJobs[i] === 'string' ? { id: ssJobs[i], lang: null } : ssJobs[i];
        try {
          const resp = await api(`/jobs/${jobRef.id}`);
          if (resp.ok) {
            const job = await resp.json();
            jobRef.status = job.status;
            jobRef.output_url = job.output_url;
            jobRef.error_message = job.error_message;
            jobRef.gameplay_key = job.gameplay_key;
            if (job.status === 'pending' || job.status === 'processing') anyActive = true;
          }
        } catch(e) {}
        // Normalize to object form
        if (typeof ssJobs[i] === 'string') {
          ssJobs[i] = jobRef;
        }
      }
    }
  }

  renderPipelineResults();

  if (anyActive) {
    setTimeout(pollPipeline, 4000);
  } else {
    loadCredits();
  }
}
```

- [ ] **Step 2: Add renderPipelineResults function**

```javascript
function renderPipelineResults() {
  if (!pipelineState) return;
  const container = document.getElementById('pipelineResults');
  let html = '';

  for (const [clipKey, entry] of Object.entries(pipelineState.clips)) {
    const clipName = entry.clipData ?
      (entry.clipData.hook_text || '').substring(0, 60) + (entry.clipData.hook_text?.length > 60 ? '...' : '') :
      clipKey.split('/').pop();
    const clipDur = entry.clipData ? `(${entry.clipData.duration.toFixed(0)}s)` : '';

    html += `<div class="result-clip-group">`;
    html += `<div class="result-clip-header">${clipName} ${clipDur}</div>`;

    // Dubbing outputs
    if (entry.dubbingOutputs.length > 0) {
      html += `<div class="result-stage-label">DUB</div>`;
      for (const o of entry.dubbingOutputs) {
        html += `<div class="result-row">
          <div class="dot ${statusToDotClass(o.status)}"></div>
          <div class="label">${langLabel(o.language)}</div>
          <div class="status-text">${o.status}</div>
          <div class="result-actions">
            ${o.status === 'completed' && o.download_url ?
              `<button onclick="previewVideo('${o.download_url}')">WATCH</button>
               <a href="${o.download_url}" download>DL</a>` : ''}
            ${o.status === 'failed' ? `<span style="color:#ef4444;font-size:11px;">${(o.error_message||'').substring(0,30)}</span>` : ''}
          </div>
        </div>`;
      }
    }

    // Splitscreen outputs (handle both string and object forms)
    const ssJobs = entry.splitscreenJobIds.map(j => typeof j === 'string' ? { id: j, lang: null, status: 'pending' } : j);
    if (ssJobs.length > 0) {
      html += `<div class="result-stage-label">SPLITSCREEN</div>`;
      for (const j of ssJobs) {
        const gpName = j.gameplay_key ? j.gameplay_key.split('/').pop() : 'gameplay';
        const langSuffix = j.lang ? ` + ${langLabel(j.lang)}` : ' + Original';
        html += `<div class="result-row">
          <div class="dot ${statusToDotClass(j.status || 'pending')}"></div>
          <div class="label">${gpName}${langSuffix}</div>
          <div class="status-text">${j.status || 'pending'}</div>
          <div class="result-actions">
            ${j.status === 'completed' && j.output_url ?
              `<button onclick="previewVideo('${j.output_url}')">WATCH</button>
               <a href="${j.output_url}" download>DL</a>` : ''}
            ${j.status === 'failed' ? `<span style="color:#ef4444;font-size:11px;">${(j.error_message||'').substring(0,30)}</span>` : ''}
          </div>
        </div>`;
      }
    }

    html += `</div>`;
  }

  container.innerHTML = html;
}

function statusToDotClass(status) {
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  if (status === 'pending') return 'pending';
  return 'processing'; // dubbing, lip_syncing, processing, downloading
}

function langLabel(code) {
  const map = { es: 'Spanish', fr: 'French', he: 'Hebrew' };
  return map[code] || code;
}
```

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add pipeline polling and results rendering"
```

---

### Task 9: Clean up startOver and verify end-to-end

**Files:**
- Modify: `app/static/index.html` — `startOver()` function

- [ ] **Step 1: Update startOver to reset pipeline state**

Find the `startOver()` function and add pipeline state cleanup:

```javascript
function startOver() {
  currentExtraction = null;
  selectedClips.clear();
  selectedGameplay.clear();
  // Reset pipeline state
  pipelineState = null;
  dubEnabled = false;
  splitscreenEnabled = false;
  selectedLanguages.clear();
  useDubbedAudio = true;
  document.getElementById('youtubeUrl').value = '';
  showStep(1);
}
```

- [ ] **Step 2: Test full flow**

1. Open dashboard, login
2. Paste a YouTube URL, extract clips
3. Select clips, click NEXT
4. Should see two stage cards (DUB + SPLITSCREEN), both collapsed
5. Toggle DUB on → language buttons appear
6. Toggle SPLITSCREEN on → gameplay grid + caption settings appear
7. Select a language + a gameplay → credit summary updates
8. "Use dubbed audio for splitscreen" toggle appears
9. GENERATE button enables when valid
10. Click GENERATE → should navigate to results view and start polling

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html
git commit -m "feat: reset pipeline state in startOver and verify flow"
```

---

### Task 10: Update Library tab to show dubbing outputs

**Files:**
- Modify: `app/static/index.html` — `renderLibraryDetail()` and related functions

- [ ] **Step 1: Add dubbing section to library detail view HTML**

In the library detail view HTML (around line 682), add a dubbing section after the clips grid and before the caption layout:

Find the `<div class="caption-layout" id="libCaptionSettings">` line and add before it:

```html
<div class="section-label" style="font-size:11px;color:#555;letter-spacing:2px;margin:16px 0 10px;font-weight:700;">DUBBING JOBS</div>
<div id="libDubbingJobs"></div>
```

- [ ] **Step 2: Add function to load and render dubbing jobs for a library extraction**

```javascript
async function loadLibDubbingJobs() {
  if (!libCurrentExtraction) return;
  const container = document.getElementById('libDubbingJobs');
  if (!container) return;

  // Get all user's dubbing jobs and filter by matching preview URLs
  try {
    const resp = await api('/dubbing');
    if (!resp.ok) { container.innerHTML = ''; return; }
    const data = await resp.json();

    // Build set of preview URLs for clips in this extraction
    const clipUrls = new Set();
    (libCurrentExtraction.clips || []).forEach(c => {
      if (c.preview_url) clipUrls.add(c.preview_url);
    });

    // Filter dubbing jobs whose source_url matches a clip preview_url
    const relevantJobs = (data.jobs || []).filter(j => clipUrls.has(j.source_url));

    if (relevantJobs.length === 0) {
      container.innerHTML = '<p style="color:#555;font-size:12px;padding:4px 0;">No dubbing jobs for these clips.</p>';
      return;
    }

    // For each relevant job, fetch full detail to get outputs
    let html = '';
    for (const summary of relevantJobs) {
      const detailResp = await api(`/dubbing/${summary.id}`);
      if (!detailResp.ok) continue;
      const job = await detailResp.json();

      html += `<div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:4px;padding:12px 16px;margin-bottom:8px;">`;
      html += `<div style="font-size:12px;color:#666;margin-bottom:8px;">Languages: ${job.languages.join(', ')} — <span class="status-badge ${job.status}">${job.status.toUpperCase()}</span></div>`;

      for (const o of (job.outputs || [])) {
        html += `<div class="result-row">
          <div class="dot ${statusToDotClass(o.status)}"></div>
          <div class="label">${langLabel(o.language)}</div>
          <div class="status-text">${o.status}</div>
          <div class="result-actions">
            ${o.status === 'completed' && o.download_url ?
              `<button onclick="previewVideo('${o.download_url}')" style="background:#ff3a2f;color:#fff;border:none;padding:5px 10px;border-radius:3px;cursor:pointer;font-family:inherit;font-size:11px;">WATCH</button>
               <a href="${o.download_url}" download style="color:#666;font-size:11px;text-decoration:none;border:1px solid #333;padding:5px 10px;border-radius:3px;">DL</a>` : ''}
          </div>
        </div>`;
      }
      html += `</div>`;
    }

    container.innerHTML = html;
  } catch(e) {
    console.error('Failed to load dubbing jobs for library', e);
    container.innerHTML = '';
  }
}
```

- [ ] **Step 3: Call loadLibDubbingJobs from renderLibraryDetail**

In the `renderLibraryDetail()` function, add this call after `renderLibClips`:

```javascript
// After renderLibClips(ext.clips || []);
loadLibDubbingJobs();
```

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat: show dubbing jobs in Library tab extraction detail"
```

---

### Task 11: Final verification and cleanup

**Files:**
- Modify: `app/static/index.html`

This task adds the ability to see all dubbing jobs from the Library list view, not just per-extraction.

- [ ] **Step 1: Add a "source" indicator on library cards for extractions that have dubbing jobs**

This is a nice-to-have. Skip for now — the per-extraction dubbing section from Task 9 covers the core requirement.

- [ ] **Step 2: Verify the full end-to-end flow works**

Test this sequence:
1. Login
2. Paste YouTube URL → Extract clips
3. Select clips → NEXT
4. Toggle DUB on → select Spanish
5. Toggle SPLITSCREEN on → select a gameplay
6. Leave "Use dubbed audio for splitscreen" on
7. Click GENERATE
8. Watch results: dubbing should show first, then splitscreen jobs should appear as dubbing outputs complete
9. Go to Library tab → open the extraction → should see dubbing jobs section

- [ ] **Step 3: Commit any final fixes**

```bash
git add app/static/index.html
git commit -m "feat: finalize pipeline dashboard end-to-end flow"
```
