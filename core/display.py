"""
Claude Code style display — clean panels, no raw tool JSON.
"""
import sys
import difflib
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich import box

console = Console()

def show_thinking():
    """Return a Live spinner context for thinking state."""
    return Live(
        Spinner("dots", text=" Thinking...", style="dim"),
        console=console,
        refresh_per_second=10,
        transient=True,
    )

def show_file_write(path, content, old_content=None):
    """Show a file write as a syntax-highlighted panel."""
    fname = Path(path).name
    ext = Path(path).suffix.lstrip('.')
    lang_map = {
        'py': 'python', 'js': 'javascript', 'ts': 'typescript',
        'sh': 'bash', 'json': 'json', 'md': 'markdown',
        'yaml': 'yaml', 'yml': 'yaml', 'toml': 'toml',
    }
    lang = lang_map.get(ext, 'text')
    if old_content:
        # Show as diff
        old_lines = old_content.splitlines(keepends=True)
        new_lines = content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
        if diff:
            diff_text = Text()
            for line in diff[2:]:  # skip --- +++ headers
                if line.startswith('+'):
                    diff_text.append(line + '\n', style='green')
                elif line.startswith('-'):
                    diff_text.append(line + '\n', style='red')
                elif line.startswith('@@'):
                    diff_text.append(line + '\n', style='cyan')
                else:
                    diff_text.append(line + '\n', style='dim')
            console.print(Panel(diff_text, title=f'Editing {fname}',
                               border_style='yellow', box=box.ROUNDED))
        return
    # New file — show with syntax highlighting
    lines_count = len(content.splitlines())
    preview = content if lines_count <= 40 else '\n'.join(content.splitlines()[:40]) + f'\n... ({lines_count - 40} more lines)'
    syntax = Syntax(preview, lang, theme='monokai', line_numbers=True)
    console.print(Panel(syntax, title=f'Creating {fname}',
                       border_style='green', box=box.ROUNDED))

def show_patch(path, old_str, new_str):
    """Show a patch operation as a mini diff."""
    fname = Path(path).name
    diff_text = Text()
    for line in old_str.splitlines():
        diff_text.append(f'- {line}\n', style='red')
    for line in new_str.splitlines():
        diff_text.append(f'+ {line}\n', style='green')
    console.print(Panel(diff_text, title=f'Patching {fname}',
                       border_style='yellow', box=box.ROUNDED))

def show_shell(command, output, error=False):
    """Show shell command and its output."""
    content = Text()
    content.append(f'$ {command}\n', style='bold cyan')
    if output.strip():
        style = 'red' if error else 'white'
        content.append(output.strip(), style=style)
    else:
        content.append('(no output)', style='dim')
    border = 'red' if error else 'blue'
    console.print(Panel(content, title='Shell',
                       border_style=border, box=box.ROUNDED))

def show_tool_generic(name, args, result):
    """Show any other tool call cleanly."""
    content = Text()
    for k, v in args.items():
        content.append(f'{k}: ', style='bold')
        content.append(f'{str(v)[:80]}\n', style='dim')
    if result and result.strip():
        content.append(result[:200], style='white')
    console.print(Panel(content, title=name.replace('_', ' ').title(),
                       border_style='dim', box=box.ROUNDED))

def show_response(text):
    """Show the final AI response cleanly."""
    console.print()
    console.print(f'  [bold green]✓[/bold green]  {text}')
    console.print()

def show_error(text):
    """Show an error message."""
    console.print(f'  [bold red]✗[/bold red]  {text}')

def show_tdd_status(iteration, max_iter, passed, failed, total):
    """Show TDD loop progress."""
    bar_width = 20
    filled = int((passed / total) * bar_width) if total > 0 else 0
    bar = '█' * filled + '░' * (bar_width - filled)
    console.print(f'  [dim]Iteration {iteration}/{max_iter}  [/dim]'
                  f'[green]{bar}[/green]  '
                  f'[green]{passed} passed[/green] '
                  f'[red]{failed} failed[/red] / {total} total')

def show_tdd_failure(test_name, error_text):
    """Show a test failure clearly."""
    content = Text()
    content.append(f'{test_name}\n', style='bold red')
    content.append(error_text[:400], style='red')
    console.print(Panel(content, title='Test Failure',
                       border_style='red', box=box.ROUNDED))

def show_tdd_complete(passed, total, iterations):
    """Show TDD completion summary."""
    if passed == total:
        console.print(Panel(
            f'[green]All {total} tests passing[/green] after {iterations} iteration(s)',
            title='[green]Tests Pass[/green]', border_style='green', box=box.ROUNDED
        ))
    else:
        console.print(Panel(
            f'[yellow]{passed}/{total} tests passing[/yellow] after {iterations} iteration(s)',
            title='[yellow]Partial Pass[/yellow]', border_style='yellow', box=box.ROUNDED
        ))

# ── Task queue display ───────────────────────────────────────

from rich.table import Table
from rich.live import Live as _Live

_task_live = None

def _build_task_panel(queue):
    """Build a rich panel showing task checklist."""
    from core.taskqueue import STATUS_DONE, STATUS_RUNNING, STATUS_FAILED, STATUS_PENDING
    text = Text.from_markup('')
    for t in queue.tasks:
        if t.status == STATUS_DONE:
            icon = '[green]✓[/green]'  # markup
            style = 'dim'
        elif t.status == STATUS_RUNNING:
            icon = '[cyan]⠸[/cyan]'  # markup
            style = 'bold'
        elif t.status == STATUS_FAILED:
            icon = '[red]✗[/red]'  # markup
            style = 'red'
        else:
            icon = '[dim]☐[/dim]'  # markup
            style = 'dim'
        done = queue.done_count()
        total = len(queue.tasks)
        line = f'  {icon}  {t.id}. {t.description[:50]}'
        if t.status == STATUS_DONE and t.result:
            line += f' [dim]→ {t.result[:40]}[/dim]'
        text.append_text(Text.from_markup(line + '\n'))
    done = queue.done_count()
    total = len(queue.tasks)
    title = f'Task Plan  [dim]{done}/{total}[/dim]'
    return Panel(text, title=title, border_style='cyan', box=box.ROUNDED)

def show_task_plan(queue):
    """Print initial task plan (static)."""
    console.print(_build_task_panel(queue))
    console.print()

def update_task_display(queue):
    """Reprint the task panel in place."""
    console.print(_build_task_panel(queue))
