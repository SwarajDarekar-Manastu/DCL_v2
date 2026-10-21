<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import RetrievalLab from '$lib/components/benchmark/RetrievalLab.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<h1>Retrieval lab</h1>
	<p class="intro">One retrieval with its legs, path and scores, to tune ef_search, RRF k and rerank depth (file 08 §5.5).</p>
	<RetrievalLab />
</RoleGate>

<style>
	h1 {
		font-size: 1.1rem;
	}
	.intro {
		font-size: 0.84rem;
		opacity: 0.8;
	}
</style>
