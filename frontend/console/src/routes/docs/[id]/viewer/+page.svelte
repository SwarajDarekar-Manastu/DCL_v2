<script lang="ts">
	import { page } from '$app/state';
	import { ApiError, getViewer, type ViewerPayload } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import DocumentViewer from '$lib/components/viewer/DocumentViewer.svelte';

	let docId = $derived(page.params.id ?? '');
	let anchor = $derived(page.url.searchParams.get('anchor') ?? '');
	let translating = $state(false);
	let payload = $state<ViewerPayload | null>(null);
	let error = $state('');

	$effect(() => {
		const [id, a, t] = [docId, anchor, translating];
		let cancelled = false;
		error = '';
		getViewer(id, a, t)
			.then((result) => {
				if (!cancelled) payload = result;
			})
			.catch((e) => {
				if (cancelled) return;
				payload = null;
				error =
					e instanceof ApiError && e.status === 501
						? 'The viewer backend is not connected yet.'
						: e instanceof ApiError
							? e.detail
							: String(e);
			});
		return () => {
			cancelled = true;
		};
	});

	const pageHref = (pageNo: number) => `/docs/${encodeURIComponent(docId)}/viewer?anchor=${encodeURIComponent(`page:${pageNo}:`)}`;
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	{#if error}
		<p role="alert">{error}</p>
	{:else if payload}
		<DocumentViewer {payload} {translating} onToggleTranslate={() => (translating = !translating)} {pageHref} />
	{:else}
		<p>Loading document…</p>
	{/if}
</RoleGate>
