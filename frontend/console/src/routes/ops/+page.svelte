<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<h1>Ops</h1>
	<p>Sync status, queue depths, failed tasks and cost today (file 08 §4.2).</p>
</RoleGate>
