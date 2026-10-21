<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="admin">
	<h1>Settings</h1>
	<p>Configuration over pipeline_config with history and rollback (file 08 §3.2).</p>
</RoleGate>
