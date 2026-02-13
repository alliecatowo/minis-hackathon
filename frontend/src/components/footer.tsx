import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-border/50 bg-background/80">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 py-8 sm:flex-row sm:justify-between">
        <Link href="/" className="font-mono text-lg font-bold tracking-tight">
          minis
        </Link>
        <nav className="flex items-center gap-6">
          <Link
            href="/features"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Features
          </Link>
          <Link
            href="/pricing"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Pricing
          </Link>
          <Link
            href="/gallery"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Gallery
          </Link>
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            GitHub
          </a>
        </nav>
        <p className="text-xs text-muted-foreground">
          Built for Dev_Dash 2026
        </p>
      </div>
    </footer>
  );
}
