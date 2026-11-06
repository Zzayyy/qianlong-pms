<script setup lang="ts">
import { useRouter } from 'vue-router'

/** 无权限页：菜单已按权限隐藏，直接输入地址时兜底提示。 */
const router = useRouter()
</script>

<template>
  <el-result icon="warning" title="403 无权访问" sub-title="当前账号没有该页面的权限，请联系管理员授权">
    <template #extra>
      <el-button type="primary" @click="router.push('/dashboard')">返回看板</el-button>
    </template>
  </el-result>
</template>
