<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<h1>Benchmark</h1>
	<p>Suites, runs and results arrive with milestone M10 (file 08 §5).</p>
</RoleGate>
