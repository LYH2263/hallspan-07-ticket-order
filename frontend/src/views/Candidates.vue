<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const drafts = ref<Record<number, string>>({})
const errors = ref<Record<number, string>>({})
const saving = ref<Set<number>>(new Set())

async function load() {
  rows.value = await api('/candidates')
  for (const r of rows.value) drafts.value[r.id] = r.ticket_no
}
onMounted(load)

async function save(r: any) {
  const ticket = (drafts.value[r.id] ?? '').trim()
  errors.value[r.id] = ''
  if (!ticket) { errors.value[r.id] = '准考证号为空，整场拒绝'; return }
  saving.value.add(r.id)
  try {
    // 改号：号段、最新流水段、排座图同成功或同失败；失败后端整段回滚
    const res = await api(`/candidates/${r.id}`, {
      method: 'PUT', body: JSON.stringify({ ticket_no: ticket }),
    })
    r.ticket_no = res.candidate.ticket_no
    drafts.value[r.id] = r.ticket_no
  } catch (e: any) {
    let msg = '整段失败，流水与图已回到保存前'
    try {
      const d = JSON.parse(String(e?.message || ''))
      msg = d?.detail?.message || d?.detail?.error || msg
    } catch { /* 保留默认文案 */ }
    errors.value[r.id] = msg
    drafts.value[r.id] = r.ticket_no  // 回显保存前的号
  } finally {
    saving.value.delete(r.id)
  }
}
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">改正准考证号：号段 · 最新流水段 · 排座图 同成功或同失败；历史流水只追加，不改写</p>
  <div class="hs-clipboard" style="max-width:520px">
    <h2>考生名册 · Clipboard</h2>
    <div v-for="r in rows" :key="r.id" class="hs-roster-row" style="flex-wrap:wrap">
      <div>
        <div>{{ r.name }}</div>
        <div class="hs-ticket">{{ r.ticket_no }}</div>
        <div v-if="errors[r.id]" class="hs-err" style="color:#c0392b;font-size:12px">{{ errors[r.id] }}</div>
      </div>
      <div style="display:flex;gap:6px;align-items:center">
        <input v-model="drafts[r.id]" style="width:130px" :aria-label="'改号 ' + r.name" />
        <button class="btn" style="padding:2px 10px" :disabled="saving.has(r.id)" @click="save(r)">改号</button>
      </div>
    </div>
  </div>
</template>
