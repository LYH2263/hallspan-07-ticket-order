<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const candidates = ref<any[]>([])
const journal = ref<any>(null)
const violKeys = ref<Set<string>>(new Set())
async function run() {
  data.value = await api('/seating/run?hall_id=1', { method: 'POST' })
  try { journal.value = await api('/seating/journal?hall_id=1') } catch { journal.value = null }
  try {
    const v = await api('/seating/violations?hall_id=1')
    const keys = new Set<string>()
    for (const x of v.violations || []) {
      if (x.a_id != null) keys.add(String(x.a_id))
      if (x.b_id != null) keys.add(String(x.b_id))
    }
    violKeys.value = keys
  } catch { violKeys.value = new Set() }
}
onMounted(async () => {
  candidates.value = await api('/candidates')
  await run()
})
const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      out.push(map.get(r + ',' + c) || { empty: true, row: r, col: c })
    }
  }
  return out
})
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左侧考生名册夹板 · 违规课桌高亮</p>
  <button class="btn" @click="run">重新排座</button>
  <p v-if="data" class="sub" style="margin-top:6px">
    重放校验：
    <strong :style="{ color: data.replay_ok ? '#1e8e3e' : '#c0392b' }">
      {{ data.replay_ok ? '流水可重放当前图 ✓' : '流水与图不一致 ✗（该段已作废）' }}
    </strong>
  </p>
  <div class="hs-classroom" style="margin-top:0.85rem">
    <aside class="hs-clipboard">
      <h2>考生名册</h2>
      <div v-for="c in candidates" :key="c.id" class="hs-roster-row">
        <div>
          <div>{{ c.name }}</div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }}</div>
      </div>
    </aside>
    <div class="hs-desk-stage" v-if="data">
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{ empty: cell.empty, 'hs-viol': isViol(cell) }"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
  <div class="card" v-if="journal && journal.entries && journal.entries.length" style="margin-top:1rem;max-width:720px">
    <h3 style="margin:0 0 6px">
      占座流水账（只追加）· 段 #{{ journal.plan_id }}
      <span :style="{ color: journal.replay_ok ? '#1e8e3e' : '#c0392b', fontSize: '12px' }">
        {{ journal.replay_ok ? '可重放当前图' : '重放失败' }}
      </span>
    </h3>
    <p class="muted" style="font-size:12px;margin:0 0 8px">
      每次成功排座按准考证升序追加一行（准考证号 · 格子 · 次序）；只追加，不回头改写先号的格子。
    </p>
    <table>
      <thead><tr><th>次序</th><th>准考证号</th><th>格子(排,列)</th><th>尾号</th></tr></thead>
      <tbody>
        <tr v-for="e in journal.entries" :key="e.seq">
          <td>{{ e.seq }}</td>
          <td>{{ e.ticket_no }}</td>
          <td>{{ e.row }}, {{ e.col }}</td>
          <td>{{ e.ticket_no.trim().slice(-1) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
