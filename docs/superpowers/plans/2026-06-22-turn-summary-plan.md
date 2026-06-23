# 回合总结与诏令暂存系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现诏令暂存机制（多条诏令汇总后一次性执行），并以结构化卡片展示回合结果，财政变化高亮显示。

**Architecture:** 纯前端改动，仅修改 `src/web/templates/index.html`。后端接口不变——多条诏令合并为多行文本后通过现有 `/next_turn` 接口发送。回合结果数据已由 `TurnSummary` 提供，前端重新组织渲染方式。

**Tech Stack:** HTML/CSS/JavaScript (vanilla, Jinja2 template)

---

### Task 1: 诏令暂存机制 — HTML 结构改造

**Files:**
- Modify: `src/web/templates/index.html:212-215`（表单区域）
- Modify: `src/web/templates/index.html:209-219`（玩家回合面板）

- [ ] **Step 1: 改造表单 HTML**

将现有的单按钮表单改为双按钮布局：输入框 + "颁诏"按钮 + "下一回合"按钮。在表单下方添加"待颁诏书"展示区域。

修改 `index.html:212-215`：

```html
    <h2>玩家回合</h2>
    <div class="status" id="status" style="margin-bottom:0.4rem">可下诏、对话百官、招募、科举，然后点"下一回合"推进推演</div>
    <form id="edict-form" onsubmit="return false;">
      <div style="display:flex;gap:0.5rem;margin-bottom:0.5rem">
        <input type="text" id="edict-input" placeholder="输入诏令…" autocomplete="off" style="flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.6rem;font-size:0.95rem" />
        <button type="button" id="issue-btn" onclick="issueEdict()" style="background:var(--accent);color:var(--bg);border:none;padding:0.6rem 1rem;font-size:0.95rem;cursor:pointer;letter-spacing:2px">颁诏</button>
      </div>
      <div id="pending-edicts" style="display:none;margin-bottom:0.5rem;background:var(--bg);border:1px solid var(--accent);padding:0.5rem;font-size:0.85rem">
        <div style="color:var(--accent);margin-bottom:0.3rem;font-weight:bold">📜 待颁诏书</div>
        <div id="pending-list"></div>
        <div style="display:flex;gap:0.5rem;margin-top:0.4rem">
          <button type="button" onclick="clearEdicts()" style="background:none;border:1px solid var(--muted);color:var(--muted);padding:0.2rem 0.6rem;cursor:pointer;font-size:0.8rem">清空</button>
          <button type="button" id="submit-btn" onclick="nextTurn()" style="background:var(--accent);color:var(--bg);border:none;padding:0.3rem 1rem;font-size:0.9rem;cursor:pointer;letter-spacing:2px;margin-left:auto">下一回合 ▶</button>
        </div>
      </div>
    </form>
```

- [ ] **Step 2: 添加待颁诏令相关 CSS**

在 `index.html` 的 `<style>` 区域（约第 133 行之前）添加待颁诏令样式：

```css
    .pending-item { display:flex; justify-content:space-between; align-items:center; padding:0.2rem 0; border-bottom:1px dashed var(--border); }
    .pending-item:last-child { border-bottom:none; }
    .pending-item .idx { color:var(--accent); margin-right:0.4rem; }
    .pending-item .text { flex:1; color:var(--text); }
    .pending-item .remove { background:none; border:none; color:var(--danger); cursor:pointer; font-size:0.8rem; padding:0 0.3rem; }
```

- [ ] **Step 3: 添加待颁诏令 JavaScript 逻辑**

在 `index.html` 的 `<script>` 区域（约第 530 行之前）添加：

```javascript
    // ---- 诏令暂存 ----
    let pendingEdicts = [];

    function issueEdict() {
      const input = document.getElementById('edict-input');
      const text = input.value.trim();
      if (!text) return;
      pendingEdicts.push(text);
      input.value = '';
      renderPendingEdicts();
    }

    function removeEdict(index) {
      pendingEdicts.splice(index, 1);
      renderPendingEdicts();
    }

    function clearEdicts() {
      pendingEdicts = [];
      renderPendingEdicts();
    }

    function renderPendingEdicts() {
      const container = document.getElementById('pending-edicts');
      const list = document.getElementById('pending-list');
      if (pendingEdicts.length === 0) {
        container.style.display = 'none';
        return;
      }
      container.style.display = 'block';
      list.innerHTML = pendingEdicts.map((e, i) =>
        `<div class="pending-item"><span class="idx">${i+1}.</span><span class="text">${e}</span><button class="remove" onclick="removeEdict(${i})">✕</button></div>`
      ).join('');
    }
```

- [ ] **Step 4: 验证**

Run: 启动服务器，打开页面，确认输入诏令后点"颁诏"按钮能看到待颁列表，可撤销，可清空。

---

### Task 2: 改造 nextTurn 函数 — 合并诏令 + 结构化结果渲染

**Files:**
- Modify: `src/web/templates/index.html:534-593`（nextTurn 函数）
- Modify: `src/web/templates/index.html:677-731`（runCourtEnd 函数）

- [ ] **Step 1: 修改 nextTurn 函数**

将 `nextTurn` 函数改为从 `pendingEdicts` 获取诏令，合并为多行文本发送。同时修改回合展示方式，为结构化卡片做准备。

```javascript
    async function nextTurn() {
      const btn = document.getElementById('submit-btn');
      btn.disabled = true;
      document.getElementById('status').textContent = '早朝开始…';

      // 合并待颁诏令
      const edictText = pendingEdicts.length > 0
        ? pendingEdicts.map((e, i) => `${i+1}. ${e}`).join('\n')
        : '';
      pendingEdicts = [];
      renderPendingEdicts();

      // 创建回合展示区域
      const turn = document.createElement('div'); turn.className = 'turn'; turn.id = 'current-turn';
      document.getElementById('dialog').prepend(turn);
      turn.innerHTML = '<div class="meta">推演中…</div>';

      try {
        const fd = new FormData();
        if (edictText) fd.append('edict', edictText);
        const resp = await fetch('/next_turn', { method: 'POST', body: fd });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let html = '';
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true});
          const lines = buffer.split('\n');
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice(6).trim();
            if (payload === '[DONE]') continue;
            try {
              const evt = JSON.parse(payload);
              if (evt.type === 'court_round') {
                html += renderCourtRound(evt.data);
                courtActive = evt.data.can_interject;
                if (courtActive) showCourtInput(turn);
              } else if (evt.type === 'court_skip') {
                courtActive = false;
                turn.innerHTML = '';  // 清空"推演中"，由 runCourtEnd 渲染
                await runCourtEnd(turn, edictText);
                return;
              }
            } catch(e) {}
          }
          turn.innerHTML = html || '<div class="meta">推演中…</div>';
        }
        turn.innerHTML = html;
        if (courtActive && !document.getElementById('court-input-area')) showCourtInput(turn);
        else if (!courtActive) await runCourtEnd(turn, edictText);
      } catch (err) {
        turn.innerHTML = '<div class="narrative">推演失败：' + err + '</div>';
      } finally {
        btn.disabled = false;
        document.getElementById('status').textContent = courtActive ? '早朝进行中，可插话或结束早朝' : '可下诏、对话百官、招募、科举，然后点"下一回合"推进推演';
      }
    }
```

- [ ] **Step 2: 修改 runCourtEnd 函数 — 结构化渲染**

将 `runCourtEnd` 函数改为在收到所有 SSE 事件后，统一渲染为结构化卡片格式。

```javascript
    async function runCourtEnd(turn, edictText) {
      document.getElementById('status').textContent = '推演中…';
      document.getElementById('submit-btn').disabled = true;
      const ending = document.getElementById('court-ending');
      if (ending) ending.remove();
      const baseHtml = turn ? turn.innerHTML : '';
      let html = baseHtml;

      // 收集所有 SSE 数据
      let narrative = '', executionList = [], deltaApplied = {}, deltaClipped = {};
      let newEvents = [], resolvedEvents = [], failDelta = {}, audienceList = [];

      try {
        const resp = await fetch('/court/end', { method: 'POST' });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true});
          const lines = buffer.split('\n');
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice(6).trim();
            if (payload === '[DONE]') continue;
            try {
              const evt = JSON.parse(payload);
              const t = evt.type, d = evt.data;
              if (t === 'narrative') narrative = d || '';
              else if (t === 'execution') executionList = d || [];
              else if (t === 'delta') { deltaApplied = (d && d.applied) || {}; deltaClipped = (d && d.clipped) || {}; }
              else if (t === 'new_events') newEvents = d || [];
              else if (t === 'resolved') resolvedEvents = d || [];
              else if (t === 'fail') failDelta = d || {};
              else if (t === 'audience') audienceList = d || [];
            } catch(e) {}
          }
        }
        // 统一渲染结构化卡片
        html = renderTurnCard(edictText, baseHtml, narrative, executionList, deltaApplied, newEvents, resolvedEvents, failDelta, audienceList);
        if (turn) turn.innerHTML = html;
        refreshState();
      } catch (err) {
        if (turn) turn.innerHTML += '<div class="narrative">推演失败：' + err + '</div>';
      } finally {
        document.getElementById('submit-btn').disabled = false;
        document.getElementById('status').textContent = '可下诏、对话百官、招募、科举，然后点"下一回合"推进推演';
      }
    }
```

- [ ] **Step 3: 添加 renderTurnCard 函数**

在 `runCourtEnd` 函数之前添加新的渲染函数：

```javascript
    function renderTurnCard(edictText, courtHtml, narrative, executionList, deltaApplied, newEvents, resolvedEvents, failDelta, audienceList) {
      let html = '';

      // 诏书章节
      if (edictText) {
        html += '<div class="turn-section"><div class="section-label">📜 诏书</div>';
        html += edictText.split('\n').map(line => `<div class="edict-line">${line}</div>`).join('');
        html += '</div>';
      }

      // 早朝议政章节
      if (courtHtml) {
        html += '<div class="turn-section"><div class="section-label">🏛 早朝议政</div>';
        html += courtHtml;
        html += '</div>';
      }

      // 史官叙事章节
      if (narrative) {
        html += '<div class="turn-section"><div class="section-label">📖 史官叙事</div>';
        html += `<div class="narrative-text">${narrative}</div>`;
        html += '</div>';
      }

      // 执行奏报
      if (executionList.length) {
        html += '<div class="turn-section"><div class="section-label">📋 执行奏报</div>';
        html += executionList.map(e => `<div class="meta">${e.name}奏：${e.public}</div>`).join('');
        html += '</div>';
      }

      // 数值变化章节（含财政高亮）
      if (Object.keys(deltaApplied).length) {
        html += '<div class="turn-section"><div class="section-label">📊 数值变化</div>';
        html += renderDeltaWithHighlights(deltaApplied);
        html += '</div>';
      }

      // 事件章节
      const eventParts = [];
      if (newEvents.length) eventParts.push(`<span>⚡ 新事件：${newEvents.join('、')}</span>`);
      if (resolvedEvents.length) eventParts.push(`<span style="color:var(--good)">✅ 已平息：${resolvedEvents.join('、')}</span>`);
      if (Object.keys(failDelta).length) eventParts.push(`<span style="color:var(--danger)">⚠ 恶化：${JSON.stringify(failDelta)}</span>`);
      if (audienceList.length) eventParts.push(`<span>👥 求见：${audienceList.map(q => q.topic).join('、')}</span>`);
      if (eventParts.length) {
        html += '<div class="turn-section"><div class="section-label">📌 其他</div>';
        html += eventParts.join('<br>');
        html += '</div>';
      }

      return html;
    }
```

- [ ] **Step 4: 添加 renderDeltaWithHighlights 函数**

```javascript
    function renderDeltaWithHighlights(delta) {
      const financeKeys = ['国库', '内帑', '月收入', '月支出'];
      const importantKeys = ['民心', '军力'];
      return Object.entries(delta).map(([k, v]) => {
        const isFinance = financeKeys.includes(k);
        const isImportant = importantKeys.includes(k);
        const isNeg = v < 0;
        const isPos = v > 0;
        const sign = v > 0 ? '+' : '';
        let cls = 'delta-line';
        let icon = '';
        if (isFinance) {
          cls += isNeg ? ' delta-finance-neg' : ' delta-finance-pos';
          icon = isNeg ? '🔴 ' : '🟢 ';
        } else if (isImportant) {
          cls += isNeg ? ' delta-imp-neg' : ' delta-imp-pos';
          icon = isNeg ? '⬇ ' : '⬆ ';
        }
        return `<div class="${cls}">${icon}${k}: <span class="${isNeg ? 'neg' : 'pos'}">${sign}${v | 0}</span></div>`;
      }).join('');
    }
```

- [ ] **Step 5: 添加结构化卡片 CSS**

```css
    .turn-section { margin: 0.6rem 0; padding: 0.5rem; background: var(--bg); border-left: 3px solid var(--accent); }
    .turn-section .section-label { font-size: 0.8rem; color: var(--accent); font-weight: bold; margin-bottom: 0.3rem; letter-spacing: 1px; }
    .turn-section .narrative-text { line-height: 1.6; }
    .turn-section .edict-line { padding: 0.15rem 0; font-size: 0.88rem; }
    .delta-line.delta-finance-neg { background: #fef2f2; padding: 0.3rem 0.5rem; border-radius: 3px; margin: 0.2rem 0; }
    .delta-line.delta-finance-pos { background: #f0fdf4; padding: 0.3rem 0.5rem; border-radius: 3px; margin: 0.2rem 0; }
    .delta-line.delta-imp-neg { color: var(--danger); }
    .delta-line.delta-imp-pos { color: var(--good); }
```

---

### Task 3: 改造 courtEnd 和 courtInterject 函数

**Files:**
- Modify: `src/web/templates/index.html:668-675`（courtEnd 函数）
- Modify: `src/web/templates/index.html:623-666`（courtInterject 函数）

- [ ] **Step 1: 修改 courtEnd 函数**

将 `courtEnd` 改为传递 edictText 到 `runCourtEnd`：

```javascript
    async function courtEnd() {
      courtActive = false;
      const area = document.getElementById('court-input-area');
      if (area) area.remove();
      const turn = document.getElementById('current-turn');
      if (turn) turn.innerHTML += '<div class="meta" id="court-ending">早朝结束，推演中…</div>';
      // 从 pendingEdicts 获取诏令（早朝期间可能已清空，从已渲染的诏书区域获取）
      const edictText = pendingEdicts.length > 0
        ? pendingEdicts.map((e, i) => `${i+1}. ${e}`).join('\n')
        : '';
      pendingEdicts = [];
      renderPendingEdicts();
      await runCourtEnd(turn, edictText);
    }
```

- [ ] **Step 2: 修改 courtInterject 函数**

将 `courtInterject` 中调用 `runCourtEnd` 的部分改为传递 edictText：

```javascript
    // 在 courtInterject 函数中，找到 await runCourtEnd(turn) 这一行
    // 改为：
    // await runCourtEnd(turn, '');
    // 因为早朝结束时的诏令已在 nextTurn 中发送
```

具体修改：在 `courtInterject` 函数中，将第 657 行的 `await runCourtEnd(turn);` 改为 `await runCourtEnd(turn, '');`

---

### Task 4: 改造 renderHistory 函数 — 结构化历史展示

**Files:**
- Modify: `src/web/templates/index.html:734-760`（renderHistory 函数）

- [ ] **Step 1: 改造 renderHistory 函数**

```javascript
    async function renderHistory() {
      const s = await (await fetch('/state')).json();
      const dialog = document.getElementById('dialog');
      if (!s.history || !s.history.length) return;
      dialog.innerHTML = '';
      for (const h of s.history) {
        const turn = document.createElement('div');
        turn.className = 'turn';
        let html = '';

        // 诏书章节
        if (h.edict) {
          html += '<div class="turn-section"><div class="section-label">📜 诏书</div>';
          html += h.edict.split('\n').map(line => `<div class="edict-line">${line}</div>`).join('');
          html += '</div>';
        }

        // 早朝议政
        if (h.court_speeches && h.court_speeches.length) {
          html += '<div class="turn-section"><div class="section-label">🏛 早朝议政</div>';
          html += h.court_speeches.map(s =>
            `<div class="court-speech"><span class="speaker">${s.speaker_name}：</span>${s.public}</div>`
          ).join('');
          html += '</div>';
        }

        // 史官叙事
        if (h.narrative) {
          html += '<div class="turn-section"><div class="section-label">📖 史官叙事</div>';
          html += `<div class="narrative-text">${h.narrative}</div>`;
          html += '</div>';
        }

        // 执行奏报
        if (h.execution_public && h.execution_public.length) {
          html += '<div class="turn-section"><div class="section-label">📋 执行奏报</div>';
          html += h.execution_public.map(e => `<div class="meta">${e.name}奏：${e.public}</div>`).join('');
          html += '</div>';
        }

        // 数值变化（含财政高亮）
        if (h.delta_applied && Object.keys(h.delta_applied).length) {
          html += '<div class="turn-section"><div class="section-label">📊 数值变化</div>';
          html += renderDeltaWithHighlights(h.delta_applied);
          html += '</div>';
        }

        // 事件
        const eventParts = [];
        if (h.new_events_triggered && h.new_events_triggered.length) eventParts.push(`<span>⚡ 新事件：${h.new_events_triggered.join('、')}</span>`);
        if (h.events_resolved && h.events_resolved.length) eventParts.push(`<span style="color:var(--good)">✅ 已平息：${h.events_resolved.join('、')}</span>`);
        if (h.fail_delta && Object.keys(h.fail_delta).length) eventParts.push(`<span style="color:var(--danger)">⚠ 恶化：${JSON.stringify(h.fail_delta)}</span>`);
        if (h.audience_queue && h.audience_queue.length) eventParts.push(`<span>👥 求见：${h.audience_queue.map(q => q.topic).join('、')}</span>`);
        if (eventParts.length) {
          html += '<div class="turn-section"><div class="section-label">📌 其他</div>';
          html += eventParts.join('<br>');
          html += '</div>';
        }

        turn.innerHTML = html;
        dialog.appendChild(turn);
      }
      dialog.scrollTop = dialog.scrollHeight;
    }
```

---

### Task 5: 验证

- [ ] **Step 1: 启动服务器**

Run: 启动 speakgame 服务器

- [ ] **Step 2: 测试诏令暂存**

1. 在输入框输入"裁撤冗员"，点"颁诏" → 确认待颁列表显示
2. 再输入"赈灾拨银十万"，点"颁诏" → 确认两条都在列表中
3. 点某条的"✕" → 确认该条被移除
4. 点"清空" → 确认列表清空

- [ ] **Step 3: 测试完整回合流程**

1. 输入"裁撤冗员"，点"颁诏"
2. 输入"赈灾拨银十万"，点"颁诏"
3. 点"下一回合" → 确认早朝进行
4. 结束早朝 → 确认结构化卡片展示，包含：诏书章节、早朝章节、叙事章节、数值变化（财政高亮）
5. 确认国库/内帑/月支出等财政字段有红色/绿色高亮背景

- [ ] **Step 4: 测试回合历史**

1. 刷新页面 → 确认历史回合以结构化卡片展示
2. 确认格式与刚完成的回合一致

- [ ] **Step 5: 测试边界情况**

1. 不输入诏令直接点"下一回合" → 确认正常推进（无诏书章节）
2. 只输入一条诏令 → 确认正常显示
3. 输入超长诏令 → 确认显示正常
