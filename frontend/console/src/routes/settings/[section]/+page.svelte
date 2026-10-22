<script lang="ts">
	import Notice from '$lib/components/shell/Notice.svelte';

	let { data } = $props();
	let section = $derived(data.section);
</script>

<div class="border-b px-5 py-4">
	<h2 class="m-0 text-base">{section.title}</h2>
	<p class="text-muted-foreground m-0 mt-1 max-w-[72ch]">{section.summary}</p>
</div>
<div class="space-y-5 px-5 py-4">
	<div>
		<h3 class="eyebrow mb-2">Configuration keys</h3>
		<ul class="m-0 divide-y rounded-md border p-0">
			{#each section.keys as key (key)}
				<li class="list-none px-3 py-2"><code class="text-foreground">{key}</code></li>
			{/each}
		</ul>
	</div>
	<dl class="kv">
		<dt>When a change applies</dt>
		<dd>{section.apply}</dd>
	</dl>
	<div class="bg-muted/60 rounded-md border px-3 py-2.5">
		<Notice tone="info">Editing, history and rollback arrive with the settings API.</Notice>
	</div>
</div>
