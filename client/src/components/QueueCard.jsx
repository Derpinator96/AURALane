import { READ_FILTERS, SORTS, timeUTC } from "../worklist.js";
import { ArrowUpRightIcon, BoardIcon, CloseIcon, FilterIcon, ListIcon, SearchIcon, WorklistIcon } from "./Icons.jsx";
import { SPECIALTIES } from "./Sidebar.jsx";
import { PopoverButton, Segmented } from "./ui.jsx";

const LANE_FILTERS = ["ALL", "CRITICAL", "URGENT", "EXPEDITED", "ROUTINE"];

function Acuity({ row }) {
  if (row.lane === "ABSTAIN" || row.lane === "FAILED" || row.acuity == null) return "--";
  return Number(row.acuity).toFixed(1);
}

const findingOf = (row) => (row.lane === "FAILED" ? row.error : row.driver_label || row.abstain_reason || "--");

// Where a study's lane came from, when a person set it or set it aside.
function Provenance({ row }) {
  if (row.human_lane) return <span className="cell-note">Lane set by {row.human_lane.by_name || row.human_lane.by}</span>;
  if (row.repeat_imaging) return <span className="cell-note">Marked inadequate by {row.repeat_imaging.by_name || row.repeat_imaging.by}</span>;
  return null;
}

function Row({ row, selected, next, who, onSelect }) {
  const verdict = row.verdict ? (row.verdict.value === "agree" ? "Agreed" : "Disagreed") : "Unread";
  const state = !row.verdict ? "unread" : row.verdict.value === "agree" ? "agreed" : "disagreed";
  return (
    <div className={`study-row lane-${row.lane} ${selected ? "selected" : ""} ${next ? "next-up" : ""} ${row.overdue ? "overdue" : ""}`}
         onClick={() => onSelect(row.study)} data-testid="study-row" data-study={row.study}>
      <div className="cell-lane">
        <span className={`lanetag lane-${row.lane}`}>{row.lane_label || row.lane}</span>
        <Provenance row={row} />
      </div>
      <div className="cell-finding">
        {next && <span className="nextup">Next up</span>}
        <span className="finding-text" title={findingOf(row)}>{findingOf(row)}</span>
      </div>
      <div className="cell-patient mono-id">{row.patient_id || row.study}</div>
      <div className="cell-modality"><span className="chip chip-quiet">{row.exam || row.modality}</span></div>
      <div className="cell-status">
        <span className={`chip chip-quiet status-${state}`}><span className="dot" />{verdict}</span>
        <span className="cell-reader" data-testid="assigned">
          {who(row)}{row.overdue && <strong className="overdue-tag"> not opened</strong>}
        </span>
      </div>
      <div className="cell-time mono">{timeUTC(row.arrived)}</div>
      <div className="cell-acuity mono-id acuity"><Acuity row={row} /></div>
      <button type="button" className="circle circle-sm cell-open" aria-label={`Open ${row.patient_id || row.study}`}
              title="Open" onClick={(e) => { e.stopPropagation(); onSelect(row.study); }}>
        <ArrowUpRightIcon size={15} />
      </button>
    </div>
  );
}

function BoardCard({ row, selected, who, onSelect, clock, isCritical }) {
  return (
    <article className={`board-card ${selected ? "selected" : ""}`} data-testid="board-card" data-study={row.study}
             tabIndex={0} onClick={() => onSelect(row.study)}
             onKeyDown={(e) => { if (e.key === "Enter") onSelect(row.study); }}>
      <div className="card-top">
        <span className="board-title">{findingOf(row)}</span>
        <span className="cell-acuity mono-id acuity"><Acuity row={row} /></span>
      </div>
      <div className="board-meta">
        <span className="mono-id">{row.patient_id || row.study}</span>
        <span className="chip chip-quiet">{row.exam || row.modality}</span>
      </div>
      <div className="board-meta">
        <span>{who(row)}</span>
        <span className="mono">{timeUTC(row.arrived)} UTC</span>
      </div>
      <Provenance row={row} />
      {row.overdue && isCritical && <div className="card-alert">Not opened within {clock || "the lane clock"}</div>}
    </article>
  );
}

export default function QueueCard({
  title, data, scope, setScope, mine, pools, poolTab, setPoolTab, view, setView, filteredStudies,
  selectedStudyId, onSelect, nextUpId, query, setQuery, searchRef, filters, onlyTriage, clearTriage, recent, who,
}) {
  const emptyOwn = data.scope === "own" && data.studies.length === 0;
  const active = [filters.lane !== "ALL", filters.read !== "all", filters.sort !== "priority", filters.specialty !== "ALL"].filter(Boolean).length;
  const single = poolTab !== "ALL";
  const visible = pools.filter((p) => !single || p.pool === poolTab);
  const nothingRead = recent && filteredStudies.length === 0;

  return (
    <section className="panel queue" data-testid="queue-card" aria-label={title}>
      <div className="qhead">
        <h2 className="card-title queue-title">{title}</h2>
        <div className="qhead-right">
          {data.me && data.scope !== "own" && (
            <Segmented small label="Whose studies" value={scope} onChange={setScope} items={[
              { id: "mine", label: `My studies (${mine.length})`, testid: "scope-mine" },
              { id: "all", label: `All studies (${data.studies.length})`, testid: "scope-department" },
            ]} />
          )}
          <div className="view-toggle" role="group" aria-label="Worklist view">
            <button type="button" className="circle" aria-pressed={view === "list"} title="List view" aria-label="List view"
                    onClick={() => setView("list")} data-testid="view-list"><ListIcon size={17} /></button>
            <button type="button" className="circle" aria-pressed={view === "board"} title="Board view" aria-label="Board view"
                    onClick={() => setView("board")} data-testid="view-board"><BoardIcon size={17} /></button>
          </div>
        </div>
      </div>

      {(data.scope !== "own" || data.studies.length > 0) && (
        <div className="qtools">
          <Segmented label="Reading pool" value={poolTab} onChange={setPoolTab} items={[
            { id: "ALL", label: "All", count: filteredStudies.length, testid: "pooltab-ALL" },
            ...pools.map((p) => ({ id: p.pool, label: p.label, testid: `pooltab-${p.pool}`,
                                   count: filteredStudies.filter((r) => r.pool === p.pool).length })),
          ]} />
          <label className="searchpill">
            <SearchIcon size={16} />
            <input ref={searchRef} type="text" placeholder="Search studies" value={query} aria-label="Search"
                   onChange={(e) => setQuery(e.target.value)} className="search-input" />
            {query && (
              <button type="button" className="search-clear" aria-label="Clear search" onClick={() => setQuery("")}>
                <CloseIcon size={14} />
              </button>
            )}
          </label>
          <PopoverButton label="Filter" icon={<FilterIcon size={16} />} badge={active || null}
                         pillProps={{ "data-testid": "filter-button" }}>
            <div className="pop-field"><span>Lane</span>
              <select value={filters.lane} onChange={(e) => filters.setLane(e.target.value)} aria-label="Lane filter">
                {LANE_FILTERS.map((l) => <option key={l} value={l}>{l === "ALL" ? "All lanes" : l}</option>)}
              </select>
            </div>
            <div className="pop-field"><span>Status</span>
              <select value={filters.read} onChange={(e) => filters.setRead(e.target.value)} aria-label="Read filter">
                {Object.entries(READ_FILTERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="pop-field"><span>Modality</span>
              <div className="seg seg-sm" role="group" aria-label="Modality">
                {SPECIALTIES.map((sp) => (
                  <button key={sp.id} type="button" aria-pressed={filters.specialty === sp.id}
                          onClick={() => filters.setSpecialty(sp.id)} data-testid={`specialty-${sp.id}`}>{sp.label}</button>
                ))}
              </div>
            </div>
            <div className="pop-field"><span>Sort</span>
              <select value={filters.sort} onChange={(e) => filters.setSort(e.target.value)} aria-label="Sort">
                {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
          </PopoverButton>
          {onlyTriage && (
            <button type="button" className="pill pill-sm" onClick={clearTriage} data-testid="triage-only">
              Needs triage only <CloseIcon size={13} />
            </button>
          )}
        </div>
      )}

      {scope === "mine" && mine.length === 0 && (
        <p className="note" data-testid="mine-empty">
          Nothing is assigned to you. <button type="button" className="linklike" onClick={() => setScope("all")}>Show all studies</button>
        </p>
      )}

      {emptyOwn && (
        <div className="empty-line" data-testid="empty-worklist"><WorklistIcon size={20} />Your worklist is empty. Simulate an ingest to add studies.</div>
      )}
      {nothingRead && <div className="empty-line" data-testid="nothing-read">Nothing read yet</div>}

      {!emptyOwn && !nothingRead && view === "board" && (
        <div className="boards" data-testid="board">
          {visible.map((p) => (
            <section key={p.pool} className="pool-board" data-testid={`board-pool-${p.pool}`} aria-label={`${p.label} reading pool`}>
              {!single && (
                <div className="pool-header">
                  <h3 className="pool-title">{p.label} pool</h3>
                  <span className="chip chip-quiet">{p.sections.reduce((a, s) => a + s.rows.length, 0)} studies</span>
                </div>
              )}
              <div className="board">
                {(data.lanes || []).map((l) => {
                  const cards = p.sections.flatMap((s) => s.rows).filter((r) => r.lane === l.lane);
                  if (onlyTriage && l.lane !== "ABSTAIN") return null;
                  if (l.pinned && l.lane !== "ABSTAIN" && cards.length === 0) return null;
                  return (
                    <section key={l.lane} className={`board-col lane-${l.lane}`} data-testid={`board-col-${p.pool}-${l.lane}`}
                             aria-label={`${p.label} ${l.label}`}>
                      <h4 className="board-col-head">
                        <span className="dot" aria-hidden="true" />
                        <span className="lanename">{l.label}</span>
                        <span className="count mono">{cards.length}</span>
                        {l.clock && <span className="clock">{l.clock}</span>}
                      </h4>
                      {cards.map((row) => (
                        <BoardCard key={row.study} row={row} selected={row.study === selectedStudyId} who={who}
                                   onSelect={onSelect} clock={l.clock} isCritical={l.lane === "CRITICAL"} />
                      ))}
                    </section>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}

      {!emptyOwn && !nothingRead && view === "list" && (
        <div className={`queue-container ${single ? "single-pool" : ""}`}>
          {pools.map((p) => (
            <section key={p.pool} className="pool-group" data-testid={`pool-${p.pool}`} aria-label={`${p.label} reading pool`}
                     hidden={single && poolTab !== p.pool}>
              <div className="pool-header">
                <h3 className="pool-title">{p.label} pool</h3>
                <span className="chip chip-quiet">{p.sections.reduce((a, s) => a + s.rows.length, 0)} studies</span>
              </div>
              {p.sections.filter((s) => !(recent && s.rows.length === 0)).map((s) => (
                <section key={s.lane} className={`lane-group lane-${s.lane}`} data-testid={`section-${p.pool}-${s.lane}`}>
                  <h3 className="lane-group-heading">
                    <span className="dot" aria-hidden="true" />
                    <span className="lanename">{s.label}</span>
                    {s.clock && <span className="clock"> · {s.clock}</span>}
                    <span className="count mono"> ({s.rows.length})</span>
                  </h3>
                  {s.lane === "FAILED" && s.rows.length > 0 && (
                    <p className="lane-note">Processing did not complete. The study is still in PACS; read it there.</p>
                  )}
                  {s.rows.map((row) => (
                    <Row key={row.study} row={row} selected={row.study === selectedStudyId}
                         next={row.study === nextUpId} who={who} onSelect={onSelect} />
                  ))}
                </section>
              ))}
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
