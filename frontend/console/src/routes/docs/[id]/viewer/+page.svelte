<script lang="ts">
	import { page } from '$app/state';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import { ApiError, getViewer, type ViewerPayload } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
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
	<Page title={payload?.document.title ?? 'Document'} width="full">
		{#snippet below()}
			{#if anchor}<p class="text-muted-foreground m-0 font-mono text-xs break-all">anchor {anchor}</p>{/if}
		{/snippet}
		{#if error}
			<Notice tone="error">{error}</Notice>
		{:else if payload}
			<DocumentViewer {payload} {translating} onToggleTranslate={() => (translating = !translating)} {pageHref} />
		{:else}
			<p class="text-muted-foreground m-0 flex items-center gap-2" role="status">
				<LoaderCircleIcon class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> Loading document…
			</p>
		{/if}
	</Page>
</RoleGate>
