<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import UsersAdmin from '$lib/components/settings/UsersAdmin.svelte';
</script>

<UsersAdmin me={session.user?.email ?? ''} />
