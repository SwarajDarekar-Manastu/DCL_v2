<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<h1>Review</h1>
	<p>The review queue and case view arrive with milestone M3 (file 08 §4).</p>
</RoleGate>
