<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const viols = ref<any[]>([])
const unplaced = ref<any[]>([])
const kindLabel: Record<string, string> = {
  distance: '间距不足',
  same_paper_adjacent: '同试卷四邻相邻',
  same_ticket_tail: '同排同准考证尾号',
}
onMounted(async () => {
  const res = await api('/seating/violations?hall_id=1')
  viols.value = res.violations; unplaced.value = res.unplaced
})
</script>
<template>
  <h1>违规</h1>
  <p class="sub">间距不足、同试卷四邻相邻，或同一排出现相同准考证尾号（尾号问题与间距无关）</p>
  <div class="card">
    <table>
      <thead><tr><th>类型</th><th>考生A</th><th>考生B</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="(v,i) in viols" :key="i">
          <td>{{ kindLabel[v.kind] || v.kind }}</td><td>{{ v.a_id }}</td><td>{{ v.b_id }}</td><td>{{ v.detail }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!viols.length" class="muted">无违规</p>
  </div>
  <div class="card" v-if="unplaced.length">
    <h3>未排上</h3>
    <div v-for="u in unplaced" :key="u.id">{{ u.name }}（{{ u.ticket_no }}）</div>
  </div>
</template>
