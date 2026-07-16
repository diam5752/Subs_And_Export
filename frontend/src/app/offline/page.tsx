import Link from 'next/link';

export default function OfflinePage() {
  return (
    <main className="min-h-dvh grid place-items-center px-6 text-center">
      <div className="studio-panel max-w-lg">
        <span className="studio-kicker">SUBFRAME / OFFLINE</span>
        <h1 className="studio-title">Δεν υπάρχει σύνδεση αυτή τη στιγμή.</h1>
        <p className="studio-subtitle">
          Τα αρχεία σου παραμένουν στη συσκευή. Συνδέσου ξανά για upload, επεξεργασία και export.
        </p>
        <Link href="/" className="btn-primary inline-flex mt-6">Δοκιμή ξανά</Link>
      </div>
    </main>
  );
}
