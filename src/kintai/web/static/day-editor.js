document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.edit-btn').forEach((btn) => {
    btn.addEventListener('click', () => startEdit(btn.closest('tr')));
  });
});

async function startEdit(row) {
  const date = row.dataset.date;
  const res = await fetch(`/api/day/${date}`);
  const day = await res.json();
  renderEditForm(row, day);
}

function addSessionRow(container, session) {
  const div = document.createElement('div');
  div.className = 'session-edit-row';

  const inInput = document.createElement('input');
  inInput.type = 'time';
  inInput.className = 'session-in';
  inInput.value = session.check_in || '';

  const dash = document.createTextNode('–');

  const outInput = document.createElement('input');
  outInput.type = 'time';
  outInput.className = 'session-out';
  outInput.value = session.check_out || '';

  const nextDayLabel = document.createElement('label');
  nextDayLabel.className = 'next-day-label';
  const nextDayCheckbox = document.createElement('input');
  nextDayCheckbox.type = 'checkbox';
  nextDayCheckbox.className = 'session-next-day';
  nextDayCheckbox.checked = !!session.check_out_next_day;
  nextDayLabel.appendChild(nextDayCheckbox);
  nextDayLabel.appendChild(document.createTextNode('翌日'));

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.textContent = '削除';
  removeBtn.addEventListener('click', () => div.remove());

  div.appendChild(inInput);
  div.appendChild(dash);
  div.appendChild(outInput);
  div.appendChild(nextDayLabel);
  div.appendChild(removeBtn);
  container.appendChild(div);
}

function addBreakRow(container, brk) {
  const div = document.createElement('div');
  div.className = 'break-edit-row';

  const startInput = document.createElement('input');
  startInput.type = 'time';
  startInput.className = 'break-start';
  startInput.value = brk.start || '';

  const dash = document.createTextNode('–');

  const endInput = document.createElement('input');
  endInput.type = 'time';
  endInput.className = 'break-end';
  endInput.value = brk.end || '';

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.textContent = '削除';
  removeBtn.addEventListener('click', () => div.remove());

  div.appendChild(startInput);
  div.appendChild(dash);
  div.appendChild(endInput);
  div.appendChild(removeBtn);
  container.appendChild(div);
}

function renderEditForm(row, day) {
  const sessionsCell = row.querySelector('.sessions-cell');
  const breaksCell = row.querySelector('.breaks-cell');
  const actionsCell = row.querySelector('.actions-cell');

  sessionsCell.innerHTML = '';
  const sessions = day.sessions.length ? day.sessions : [{ check_in: '', check_out: '', check_out_next_day: false }];
  sessions.forEach((s) => addSessionRow(sessionsCell, s));

  const addSessionBtn = document.createElement('button');
  addSessionBtn.type = 'button';
  addSessionBtn.textContent = '+ セッション追加';
  addSessionBtn.addEventListener('click', () => {
    addSessionRow(sessionsCell, { check_in: '', check_out: '', check_out_next_day: false });
  });
  sessionsCell.appendChild(addSessionBtn);

  breaksCell.innerHTML = '';
  day.breaks.forEach((b) => addBreakRow(breaksCell, b));

  const addBreakBtn = document.createElement('button');
  addBreakBtn.type = 'button';
  addBreakBtn.textContent = '+ 休憩追加';
  addBreakBtn.addEventListener('click', () => addBreakRow(breaksCell, { start: '', end: '' }));
  breaksCell.appendChild(addBreakBtn);

  actionsCell.innerHTML = '';
  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'save-btn';
  saveBtn.textContent = '保存';
  saveBtn.addEventListener('click', () => saveDay(row));

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.textContent = 'キャンセル';
  cancelBtn.addEventListener('click', () => window.location.reload());

  actionsCell.appendChild(saveBtn);
  actionsCell.appendChild(cancelBtn);
}

async function saveDay(row) {
  const date = row.dataset.date;

  // check_out が空のセッションは「進行中」として扱いそのまま送る（1日に1件まで）。
  // 出勤時刻が入っていない行（未入力の追加行）だけを除外する。
  const sessions = Array.from(row.querySelectorAll('.session-edit-row'))
    .map((div) => ({
      check_in: div.querySelector('.session-in').value,
      check_out: div.querySelector('.session-out').value || null,
      check_out_next_day: div.querySelector('.session-next-day').checked,
    }))
    .filter((s) => s.check_in);

  if (sessions.length === 0) {
    alert('少なくとも1つのセッションを入力してください。');
    return;
  }

  const breaks = Array.from(row.querySelectorAll('.break-edit-row'))
    .map((div) => ({
      start: div.querySelector('.break-start').value,
      end: div.querySelector('.break-end').value,
    }))
    .filter((b) => b.start && b.end);

  const res = await fetch(`/api/day/${date}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessions, breaks }),
  });
  const result = await res.json();

  if (result.success) {
    window.location.reload();
  } else {
    alert(result.message);
  }
}
