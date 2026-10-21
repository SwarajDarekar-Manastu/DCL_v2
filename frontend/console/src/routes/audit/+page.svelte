<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<h1>Audit</h1>
	<p>Timeline of human actions from audit_events (file 08 §4.2).</p>
</RoleGate>
