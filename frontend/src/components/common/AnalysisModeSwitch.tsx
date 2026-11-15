import { Grid3x3, MapPin } from 'lucide-react'
import { NavLink } from 'react-router'

const cls = ({ isActive }: { isActive: boolean }) => `seg-item ${isActive ? 'bg-surface text-fg shadow-sm' : ''}`

/** Point ⇄ Regional analysis switch (both modes remain fully available). */
export function AnalysisModeSwitch() {
  return (
    <nav aria-label="Analysis mode" className="seg">
      <NavLink to="/explore" className={cls}>
        <MapPin className="size-4" aria-hidden /> Point
      </NavLink>
      <NavLink to="/regional" end className={cls}>
        <Grid3x3 className="size-4" aria-hidden /> Region or country
      </NavLink>
    </nav>
  )
}
