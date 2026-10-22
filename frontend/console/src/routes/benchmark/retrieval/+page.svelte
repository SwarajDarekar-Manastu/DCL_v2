<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RetrievalLab from '$lib/components/benchmark/RetrievalLab.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<Page title="Retrieval lab" description="One retrieval with its legs, path and scores, to tune ef_search, RRF k and rerank depth (file 08 §5.5)." width="full">
		<RetrievalLab />
	</Page>
</RoleGate>
