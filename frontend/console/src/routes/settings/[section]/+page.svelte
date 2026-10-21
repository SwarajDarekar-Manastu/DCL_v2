<script lang="ts">
	let { data } = $props();
	let section = $derived(data.section);
</script>

<h1>{section.title}</h1>
<p>{section.summary}</p>
<h2>Configuration keys</h2>
<ul>
	{#each section.keys as key (key)}
		<li><code>{key}</code></li>
	{/each}
</ul>
<p><strong>When a change applies:</strong> {section.apply}</p>
<p class="pending">Editing, history and rollback arrive with the settings API.</p>

<style>
	h2 {
		font-size: 1rem;
		margin-top: 1.5rem;
	}
	.pending {
		margin-top: 1.5rem;
		padding: 0.6rem 0.8rem;
		border-left: 4px solid var(--muted);
		background: var(--surface);
	}
</style>
