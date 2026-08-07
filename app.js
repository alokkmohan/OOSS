let dashboardData = null;
let districtSort = 'unclear_pct';
const RECORD_PAGE_SIZE = 200;
const DISTRICT_TARGET = 75;

// Chart Instances
let statusChart = null;
let willingnessChart = null;
let categoryChart = null;
let reasonChart = null;
let genderChart = null;

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const res = await fetch('dashboard_data.json');
    dashboardData = await res.json();
    initDashboard();
  } catch (err) {
    console.error('Error loading dashboard_data.json:', err);
  }
});

function initDashboard() {
  setupEventListeners();
  renderAll();
}

function setupEventListeners() {
  document.getElementById('district-search').addEventListener('input', (e) => {
    renderDistrictTable(e.target.value);
  });
  document.getElementById('district-sort').addEventListener('change', (e) => {
    districtSort = e.target.value;
    renderDistrictTable(document.getElementById('district-search').value);
  });
  document.getElementById('record-search').addEventListener('input', (e) => {
    renderRecordTable(e.target.value);
  });
  document.getElementById('district-download').addEventListener('click', () => {
    downloadDistrictCSV(document.getElementById('district-search').value);
  });
}

function downloadDistrictCSV(filterTerm = '') {
  const list = sortedDistricts().filter(d =>
    d.district_name.toLowerCase().includes(filterTerm.toLowerCase())
  );

  const headers = ['District Name', 'Total Surveyed', 'Known Studying', 'Known Not Studying',
    'Unclear / Pending', 'Deceased', 'Verification Rate (%)'];
  const escapeCsv = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [headers.map(escapeCsv).join(',')];
  list.forEach(d => {
    lines.push([
      d.district_name, d.total, d.studying || 0, d.not_studying || 0,
      d.unclear || 0, d.deceased || 0, d.verification_rate_pct || 0,
    ].map(escapeCsv).join(','));
  });

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `district_verification_leaderboard_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function renderAll() {
  renderGeneratedAt();
  renderKPIs();
  renderStatusChart();
  renderWillingnessChart();
  renderCategoryChart();
  renderReasonChart();
  renderGenderChart();
  renderDistrictTable();
  renderRecordTable();
}

function renderGeneratedAt() {
  const el = document.getElementById('generated-at');
  if (dashboardData.generated_at) {
    const d = new Date(dashboardData.generated_at);
    el.textContent = `Data as of ${d.toLocaleString()}`;
  }
}

function renderKPIs() {
  const s = dashboardData.summary;

  document.getElementById('kpi-total').textContent = s.total.toLocaleString();
  document.getElementById('kpi-total-sub').textContent = `${dashboardData.districts.length} Districts Reporting`;

  document.getElementById('kpi-studying').textContent = s.studying.toLocaleString();
  document.getElementById('kpi-studying-sub').textContent = `${s.studying_pct}% of Total Records`;

  document.getElementById('kpi-dropout').textContent = s.not_studying.toLocaleString();
  document.getElementById('kpi-dropout-sub').textContent = `${s.not_studying_pct}% of Total Records`;

  document.getElementById('kpi-unclear').textContent = s.unclear.toLocaleString();
  document.getElementById('kpi-unclear-sub').textContent = `${s.unclear_pct}% of Total Records`;

  const districtsReporting = dashboardData.districts.length;
  document.getElementById('kpi-districts').textContent = `${districtsReporting} / ${DISTRICT_TARGET}`;
  document.getElementById('kpi-districts-sub').textContent = `${Math.round(districtsReporting / DISTRICT_TARGET * 100)}% coverage`;
}

function renderStatusChart() {
  const ctx = document.getElementById('chart-status').getContext('2d');
  if (statusChart) statusChart.destroy();

  const s = dashboardData.summary;

  statusChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Studying', 'Not Studying', 'Unclear / Pending', 'Death Cases'],
      datasets: [{
        data: [s.studying, s.not_studying, s.unclear, s.deceased],
        backgroundColor: ['#22c55e', '#f97316', '#64748b', '#ef4444'],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#475569' } }
      },
      cutout: '70%'
    }
  });
}

function renderWillingnessChart() {
  const ctx = document.getElementById('chart-willingness').getContext('2d');
  if (willingnessChart) willingnessChart.destroy();

  const w = dashboardData.willingness;
  const unclear = dashboardData.summary.unclear;

  willingnessChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Willing (Economic/External/Unspecified)', 'Unwilling', 'Unclear'],
      datasets: [{
        data: [w.willing, w.unwilling, unclear],
        backgroundColor: ['#38bdf8', '#a855f7', '#64748b'],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#475569' } }
      },
      cutout: '70%'
    }
  });
}

function renderCategoryChart() {
  const ctx = document.getElementById('chart-category').getContext('2d');
  if (categoryChart) categoryChart.destroy();

  const catData = dashboardData.category_breakdown;
  const labels = Object.keys(catData);
  const studying = labels.map(c => catData[c]['Studying'] || 0);
  const notStudying = labels.map(c => catData[c]['Not Studying'] || 0);
  const unclear = labels.map(c => catData[c]['Unclear'] || 0);

  categoryChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        { label: 'Studying', data: studying, backgroundColor: '#22c55e' },
        { label: 'Not Studying', data: notStudying, backgroundColor: '#f97316' },
        { label: 'Unclear', data: unclear, backgroundColor: '#64748b' }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true, ticks: { color: '#475569' }, grid: { display: false } },
        y: { stacked: true, ticks: { color: '#475569' }, grid: { color: 'rgba(15,23,42,0.08)' } }
      },
      plugins: {
        legend: { labels: { color: '#475569' } }
      }
    }
  });
}

function sortedDistricts() {
  const list = [...dashboardData.districts];
  if (districtSort === 'district_name') {
    list.sort((a, b) => a.district_name.localeCompare(b.district_name));
  } else {
    list.sort((a, b) => b[districtSort] - a[districtSort]);
  }
  return list;
}

function renderReasonChart() {
  const ctx = document.getElementById('chart-reasons').getContext('2d');
  if (reasonChart) reasonChart.destroy();

  const list = dashboardData.reason_breakdown || [];
  const labels = list.map(r => r.label);
  const counts = list.map(r => r.count);

  reasonChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'No. of Students',
        data: counts,
        backgroundColor: '#0ea5e9',
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        x: { ticks: { color: '#475569' }, grid: { color: 'rgba(15,23,42,0.08)' } },
        y: { ticks: { color: '#475569' }, grid: { display: false } }
      }
    }
  });
}

function renderGenderChart() {
  const ctx = document.getElementById('chart-gender').getContext('2d');
  if (genderChart) genderChart.destroy();

  const genderData = dashboardData.gender_breakdown;
  const labels = Object.keys(genderData);
  const studying = labels.map(g => genderData[g]['Studying'] || 0);
  const notStudying = labels.map(g => genderData[g]['Not Studying'] || 0);

  genderChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        { label: 'Studying', data: studying, backgroundColor: '#22c55e', borderRadius: 4 },
        { label: 'Not Studying', data: notStudying, backgroundColor: '#ef4444', borderRadius: 4 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: '#475569' }, grid: { display: false } },
        y: { ticks: { color: '#475569' }, grid: { color: 'rgba(15,23,42,0.08)' } }
      },
      plugins: {
        legend: { labels: { color: '#475569' } }
      }
    }
  });
}

function renderDistrictTable(filterTerm = '') {
  const tbody = document.getElementById('table-district-body');
  tbody.innerHTML = '';

  const list = sortedDistricts().filter(d =>
    d.district_name.toLowerCase().includes(filterTerm.toLowerCase())
  );

  list.forEach(d => {
    const tr = document.createElement('tr');
    const rate = d.verification_rate_pct || 0;
    tr.innerHTML = `
      <td style="font-weight: 600; color: #0f172a;">${d.district_name}</td>
      <td>${d.total.toLocaleString()}</td>
      <td><span class="badge badge-green">${(d.studying || 0).toLocaleString()}</span></td>
      <td><span class="badge badge-orange">${(d.not_studying || 0).toLocaleString()}</span></td>
      <td><span class="badge badge-gray">${(d.unclear || 0).toLocaleString()}</span></td>
      <td>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width: ${Math.min(rate, 100)}%;"></div>
        </div>
        ${rate}%
      </td>
    `;
    tbody.appendChild(tr);
  });
}

const STATUS_BADGE_CLASS = {
  'Studying': 'badge-green',
  'Not Studying': 'badge-orange',
  'Unclear': 'badge-gray',
  'Deceased': 'badge-red'
};

function renderRecordTable(filterTerm = '') {
  const section = document.getElementById('record-table-section');
  if (!dashboardData.records) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';

  const tbody = document.getElementById('table-record-body');
  const footer = document.getElementById('record-table-footer');
  tbody.innerHTML = '';

  const term = filterTerm.trim().toLowerCase();
  const all = dashboardData.records;
  const filtered = term
    ? all.filter(r =>
        r.student_name.toLowerCase().includes(term) ||
        r.district.toLowerCase().includes(term) ||
        r.block.toLowerCase().includes(term) ||
        r.remark.toLowerCase().includes(term) ||
        r.current_status.toLowerCase().includes(term)
      )
    : all;

  const shown = filtered.slice(0, RECORD_PAGE_SIZE);

  shown.forEach(r => {
    const tr = document.createElement('tr');
    const badgeClass = STATUS_BADGE_CLASS[r.status] || 'badge-gray';
    tr.innerHTML = `
      <td>${r.district}</td>
      <td>${r.block}</td>
      <td style="font-weight: 600; color: #0f172a;">${r.student_name}</td>
      <td>${r.gender}</td>
      <td>${r.category}</td>
      <td>${r.class}</td>
      <td><span class="badge ${badgeClass}">${r.status}</span></td>
      <td>${r.remark}</td>
    `;
    tbody.appendChild(tr);
  });

  footer.textContent = filtered.length > RECORD_PAGE_SIZE
    ? `Showing first ${RECORD_PAGE_SIZE.toLocaleString()} of ${filtered.length.toLocaleString()} matching records — narrow your search to see more.`
    : `Showing ${filtered.length.toLocaleString()} of ${all.length.toLocaleString()} records.`;
}
