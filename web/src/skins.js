// Dark HUD skins. Every rule is scoped under .hv, so nothing reaches the rest of Hermes Desktop,
// and every asset is inlined by the build, so the page loads nothing from the network.
// RPG wood uses RPGUI's frames and buttons (zlib; public-domain art by Buch).
// PS1 blue follows PSone.css's window and button styling (MIT), with its global rules and remote
// fonts left out. Play is the only font carried over.
import woodBorder from 'rpgui/img/border-image.png'
import woodFill from 'rpgui/img/background-image.png'
import woodButton from 'rpgui/img/button.png'
import woodButtonHover from 'rpgui/img/button-hover.png'
import woodButtonDown from 'rpgui/img/button-down.png'
import goldButton from 'rpgui/img/button-golden.png'
import goldButtonHover from 'rpgui/img/button-golden-hover.png'
import goldButtonDown from 'rpgui/img/button-golden-down.png'
import playFont from 'psone.css/fonts/Play-Regular.woff'

export const SKIN_CSS = `
.hv { container-type: size; }
@container (max-height: 590px) { .hv-mini { display: none; } }
@container (max-width: 920px) { .hv-w1 { display: none !important; } }
@container (max-width: 540px) { .hv-w3 { display: none !important; } }
@container (max-width: 700px) { .hv-w2 { display: none !important; } .hv .hv-btn { padding: 5px 5px !important; font-size: 11px !important; } }
@font-face { font-family: 'HV Play'; src: url(${playFont}) format('woff'); }

.hv[data-skin="ink"] { --hv-mid: #1717e0; --hv-low: #1717e0; --hv-node: #fdfdff; background: #fdfdff !important; font-family: Georgia, 'Times New Roman', serif; }
.hv[data-skin="ink"] .hv-panel { background: #fdfdff !important; border: 2px solid #1717e0 !important; border-radius: 10px !important; backdrop-filter: none !important; }
.hv[data-skin="ink"] .hv-panel, .hv[data-skin="ink"] .hv-panel * { color: #1717e0 !important; text-shadow: none !important; }
.hv[data-skin="ink"] .hv-panel svg path { stroke: #1717e0 !important; }
.hv[data-skin="ink"] .hv-card { background: #fdfdff !important; border: 2px solid #1717e0 !important; }
.hv[data-skin="ink"] .hv-card[data-selected="true"] { background: #1717e0 !important; }
.hv[data-skin="ink"] .hv-card[data-selected="true"], .hv[data-skin="ink"] .hv-card[data-selected="true"] * { color: #fdfdff !important; }
.hv[data-skin="ink"] .hv-btn { background: #fdfdff !important; border: 2px solid #1717e0 !important; border-radius: 999px !important; font-family: ui-monospace, Consolas, monospace; font-weight: 700; }
.hv[data-skin="ink"] .hv-btn[data-on="true"], .hv[data-skin="ink"] .hv-primary { background: #1717e0 !important; }
.hv[data-skin="ink"] .hv-btn[data-on="true"], .hv[data-skin="ink"] .hv-primary, .hv[data-skin="ink"] .hv-primary * { color: #fdfdff !important; }
.hv[data-skin="ink"] .hv-mini { background: #1717e0 !important; }
.hv[data-skin="ink"] .hv-mini canvas { filter: grayscale(1) brightness(1.5) contrast(1.3); mix-blend-mode: screen; }
.hv[data-skin="ink"] .hv-feed, .hv[data-skin="ink"] .hv-feed * { color: #1717e0 !important; text-shadow: 0 0 4px #fdfdff, 0 0 4px #fdfdff !important; }
.hv[data-skin="ink"] input, .hv[data-skin="ink"] textarea { background: #fdfdff !important; border: 2px solid #1717e0 !important; }
.hv[data-skin="ink"] .hv-meter { background: rgba(23, 23, 224, 0.2) !important; }
.hv[data-skin="ink"] .hv-meter > * { background: #1717e0 !important; }

.hv[data-skin="wood"] { --hv-mid: #cdbb9b; --hv-low: #a08d71; font-family: ui-monospace, Consolas, monospace; }
.hv[data-skin="wood"] .hv-panel {
  background: linear-gradient(rgba(20, 12, 8, 0.8), rgba(20, 12, 8, 0.8)), url(${woodFill}) !important;
  background-clip: padding-box !important;
  border: 9px solid transparent !important;
  border-image: url(${woodBorder}) 6 / 12px repeat !important;
  border-radius: 0 !important;
  backdrop-filter: none !important;
  image-rendering: pixelated;
}
.hv[data-skin="wood"] .hv-card { background: rgba(0, 0, 0, 0.42) !important; border: 2px solid #5b3f2a !important; border-radius: 0 !important; }
.hv[data-skin="wood"] .hv-card[data-selected="true"] { border-color: #e6b450 !important; }
.hv[data-skin="wood"] .hv-btn {
  background: url(${woodButton}) center / 100% 100% no-repeat !important;
  border: 0 !important; border-radius: 0 !important; color: #f4e8ca !important;
  padding: 8px 15px !important; image-rendering: pixelated; text-shadow: 1px 1px 0 #000;
}
.hv[data-skin="wood"] .hv-btn:hover:not(:disabled) { background-image: url(${woodButtonHover}) !important; }
.hv[data-skin="wood"] .hv-btn:active:not(:disabled) { background-image: url(${woodButtonDown}) !important; }
.hv[data-skin="wood"] .hv-btn[data-on="true"] { color: #ffd76a !important; }
.hv[data-skin="wood"] .hv-primary { background-image: url(${goldButton}) !important; color: #2a1a06 !important; text-shadow: none; font-weight: 700; }
.hv[data-skin="wood"] .hv-primary:hover:not(:disabled) { background-image: url(${goldButtonHover}) !important; }
.hv[data-skin="wood"] .hv-primary:active:not(:disabled) { background-image: url(${goldButtonDown}) !important; }

.hv[data-skin="ps1"] { --hv-mid: #c5cbe6; --hv-low: #9aa3cc; font-family: 'HV Play', system-ui, sans-serif; }
.hv[data-skin="ps1"] .hv-panel {
  background: linear-gradient(rgba(13, 34, 137, 0.92), rgba(6, 9, 59, 0.94)) !important;
  border: 1px solid #c6c6c6 !important; border-radius: 8px !important;
  box-shadow: inset 0 0 2px 2px rgba(0, 0, 0, 0.3); backdrop-filter: none !important;
}
.hv[data-skin="ps1"] .hv-card { background: rgba(0, 0, 0, 0.3) !important; border: 1px solid rgba(198, 198, 198, 0.4) !important; }
.hv[data-skin="ps1"] .hv-card[data-selected="true"] { border-color: #fff !important; }
.hv[data-skin="ps1"] .hv-btn {
  background: linear-gradient(to right, transparent, rgba(174, 175, 174, 0.65), transparent) !important;
  border: 0 !important; border-top: 2px solid rgba(255, 255, 255, 0.22) !important; border-bottom: 2px solid rgba(255, 255, 255, 0.22) !important;
  border-radius: 0 !important; color: #fff !important; text-transform: uppercase; font-weight: 700; text-shadow: 2px 2px #000;
}
.hv[data-skin="ps1"] .hv-btn[data-on="true"] { background: linear-gradient(to right, transparent, #c99a33, transparent) !important; }
.hv[data-skin="ps1"] .hv-primary { background: linear-gradient(to right, transparent, #3e8ca5, transparent) !important; }
.hv[data-skin="ps1"] .hv-btn:hover:not(:disabled) { filter: brightness(1.25); }
`
