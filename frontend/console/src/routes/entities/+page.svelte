<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<h1>Entities</h1>
	<p>Canonical entities and alias merges (file 08 §4.2).</p>
</RoleGate>
