import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { LocationAnchor } from '../../lib/types';

const SESSION_KEY = 'sg-homeradar-advisor-session';
const money = new Intl.NumberFormat('en-SG', {
  style: 'currency',
  currency: 'SGD',
  maximumFractionDigits: 0,
});

interface Source {
  kind: 'local' | 'web';
  title: string;
  url: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  warnings?: string[];
}

interface AdvisorProfile {
  housing_mode?: 'rent' | 'buy' | 'undecided' | null;
  life_stage?: string | null;
  household_summary?: string | null;
  institution?: string | null;
  workplace?: string | null;
  preferred_towns?: string[];
  location_raw?: string | null;
  location_query?: string | null;
  location_reason?: string | null;
  location_relation?: string | null;
  location_flexibility?: string | null;
  location_confidence?: number | null;
  location_needs_clarification?: boolean;
  location_resolution_status?: 'missing' | 'recognized' | 'pending_confirmation' | 'unresolved' | 'confirmed';
  anchor_name?: string | null;
  anchor_address?: string | null;
  anchor_latitude?: number | null;
  anchor_longitude?: number | null;
  anchor_planning_area?: string | null;
  anchor_subzone?: string | null;
  max_anchor_distance_m?: number | null;
  estimated_budget?: number | null;
  max_budget?: number | null;
  budget_flexible?: boolean;
  hdb_flat_type?: string | null;
  hdb_flat_types?: string[];
  bedrooms?: number | null;
  bedroom_options?: number[];
  rental_scope?: string | null;
  room_preference_flexible?: boolean;
  transport_importance?: string | null;
  school_need?: string | null;
  childcare_need?: string | null;
  healthcare_need?: string | null;
  park_need?: string | null;
  additional_needs?: string[];
  needs_discussed?: boolean;
}

interface ProfileProgress {
  completed: number;
  total: number;
  ready: boolean;
  checks: Record<string, boolean>;
  missing: string[];
}

interface LocationCandidate {
  id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  planning_area: string;
  subzone: string;
  confidence: number;
}

interface RecommendedArea {
  id: string;
  name: string;
  planning_area?: string | null;
  subzone?: string | null;
  mode: 'rent' | 'buy';
  typical_price: number;
  price_unit: string;
  available_listings?: number | null;
  anchor_distance_m?: number | null;
  score: number;
  reasons: string[];
}

interface RecommendedListing {
  id: string;
  mode: 'rent' | 'buy';
  address?: string | null;
  title?: string | null;
  price: number;
  room_type?: string | null;
  property_type?: string | null;
  floor_area_sqft?: number | null;
  planning_area?: string | null;
  subzone?: string | null;
  nearest_mrt_name?: string | null;
  nearest_mrt_distance_m?: number | null;
  anchor_distance_m?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  reasons: string[];
}

export interface AdvisorRecommendations {
  mode: 'rent' | 'buy';
  areas: RecommendedArea[];
  listings: RecommendedListing[];
  warnings: string[];
  disclaimer?: string;
}

interface AdvisorResponse {
  session_id: string;
  reply: string;
  profile: AdvisorProfile;
  progress: ProfileProgress;
  location_candidates: LocationCandidate[];
  recommendations?: AdvisorRecommendations | null;
  sources: Source[];
  warnings?: string[];
  method?: string;
  privacy: string;
}

interface AdvisorStateResponse {
  session_id: string;
  profile: AdvisorProfile;
  progress: ProfileProgress;
  turns: Array<{ role: 'user' | 'assistant'; content: string }>;
  location_candidates: LocationCandidate[];
  privacy: string;
}

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我是你的新加坡住房顾问。你不需要已经有完整计划：可以先问我任何租房或买房问题，我会先回答，再一次只问一个关键问题，逐步整理出适合你的方案。\n\n你现在对租房还是买房更感兴趣？',
};

function titleCase(value?: string | null) {
  return (value || '').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function profileBudget(profile: AdvisorProfile) {
  if (profile.budget_flexible) return 'No upper limit';
  if (profile.max_budget == null) return 'Not set';
  return `${money.format(profile.max_budget)}${profile.housing_mode === 'rent' ? ' / month' : ''}`;
}

function profileRooms(profile: AdvisorProfile) {
  if (profile.room_preference_flexible) return 'Any room type';
  if (profile.hdb_flat_types?.length) return profile.hdb_flat_types.join(' / ');
  if (profile.hdb_flat_type) return profile.hdb_flat_type;
  if (profile.bedroom_options?.length) {
    const label = profile.bedroom_options.join(' or ');
    return profile.rental_scope === 'whole_unit' ? `${label} BR whole unit` : `${label} bedrooms`;
  }
  if (profile.rental_scope === 'room') return 'Private room';
  if (profile.rental_scope === 'whole_unit') return `${profile.bedrooms || 'Any'} BR whole unit`;
  if (profile.bedrooms) return `${profile.bedrooms} bedroom${profile.bedrooms > 1 ? 's' : ''}`;
  return 'Not set';
}

function locationStatus(profile: AdvisorProfile) {
  if (profile.location_resolution_status === 'confirmed') return 'OneMap confirmed';
  if (profile.location_resolution_status === 'pending_confirmation') return 'Recognised — confirm map point';
  if (profile.location_resolution_status === 'unresolved') return 'Recognised — OneMap unresolved';
  if (profile.location_needs_clarification) return 'Needs clarification';
  if (profile.location_reason?.startsWith('inferred')) return 'Inferred from your context';
  return '';
}

function sourceLabel(source: Source) {
  return source.kind === 'web' ? 'Web' : 'Project data';
}

export function AdvisorView({
  available,
  onAnchorChange,
  onShowMap,
  recommendations,
  onRecommendationsChange,
}: {
  available: boolean;
  onAnchorChange: (anchor: LocationAnchor | null) => void;
  onShowMap: (mode: 'sale' | 'rent', listingIds?: string[]) => void;
  recommendations: AdvisorRecommendations | null;
  onRecommendationsChange: (recommendations: AdvisorRecommendations | null) => void;
}) {
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_KEY) || '');
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [profile, setProfile] = useState<AdvisorProfile>({});
  const [progress, setProgress] = useState<ProfileProgress>({ completed: 0, total: 5, ready: false, checks: {}, missing: [] });
  const [candidates, setCandidates] = useState<LocationCandidate[]>([]);
  const [privacy, setPrivacy] = useState('Profile is kept in temporary server memory only.');
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    fetch(`/api/advisor/session?session_id=${encodeURIComponent(sessionId)}`)
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || 'Session unavailable');
        return data as AdvisorStateResponse;
      })
      .then((data) => {
        if (cancelled) return;
        setProfile(data.profile || {});
        setProgress(data.progress);
        setCandidates(data.location_candidates || []);
        setPrivacy(data.privacy);
        if (data.turns?.length) {
          setMessages(data.turns.map((turn, index) => ({ id: `restored-${index}`, ...turn })));
        }
        syncAnchor(data.profile);
      })
      .catch(() => {
        if (!cancelled) {
          localStorage.removeItem(SESSION_KEY);
          setSessionId('');
        }
      });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages, candidates, recommendations, loading]);

  function syncAnchor(nextProfile: AdvisorProfile) {
    if (nextProfile.anchor_latitude == null || nextProfile.anchor_longitude == null) return;
    onAnchorChange({
      id: `advisor:${nextProfile.anchor_latitude}:${nextProfile.anchor_longitude}`,
      provider: 'onemap',
      name: nextProfile.anchor_name || nextProfile.location_query || 'Selected place',
      address: nextProfile.anchor_address || '',
      latitude: nextProfile.anchor_latitude,
      longitude: nextProfile.anchor_longitude,
      confidence: 1,
      planningArea: nextProfile.anchor_planning_area || '',
      subzone: nextProfile.anchor_subzone || '',
      maxDistanceM: nextProfile.max_anchor_distance_m || undefined,
    });
  }

  function applyResponse(data: AdvisorResponse) {
    setSessionId(data.session_id);
    localStorage.setItem(SESSION_KEY, data.session_id);
    setProfile(data.profile || {});
    setProgress(data.progress);
    setCandidates(data.location_candidates || []);
    setPrivacy(data.privacy);
    onRecommendationsChange(data.recommendations || null);
    syncAnchor(data.profile);
    setMessages((current) => [
      ...current,
      {
        id: `assistant-${Date.now()}-${current.length}`,
        role: 'assistant',
        content: data.reply,
        sources: data.sources,
        warnings: data.warnings,
      },
    ]);
  }

  async function callAdvisor(body: Record<string, unknown>, retryExpired = true): Promise<AdvisorResponse> {
    const response = await fetch('/api/advisor/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      const message = String(data.message || 'The advisor could not complete this turn.');
      if (retryExpired && body.session_id && /session expired|not found/i.test(message)) {
        localStorage.removeItem(SESSION_KEY);
        setSessionId('');
        const retryBody = { ...body };
        delete retryBody.session_id;
        return callAdvisor(retryBody, false);
      }
      throw new Error(message);
    }
    return data as AdvisorResponse;
  }

  async function send(event?: FormEvent, override?: string) {
    event?.preventDefault();
    const content = (override ?? draft).trim();
    if (!content || loading) return;
    setDraft('');
    setError('');
    onRecommendationsChange(null);
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: 'user', content }]);
    setLoading(true);
    try {
      const body: Record<string, unknown> = { message: content };
      if (sessionId) body.session_id = sessionId;
      applyResponse(await callAdvisor(body));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Advisor request failed.');
    } finally {
      setLoading(false);
    }
  }

  async function confirmLocation(candidate: LocationCandidate) {
    if (loading) return;
    setLoading(true);
    setError('');
    setMessages((current) => [...current, {
      id: `user-location-${Date.now()}`,
      role: 'user',
      content: `确认地点：${candidate.name}`,
    }]);
    try {
      applyResponse(await callAdvisor({
        session_id: sessionId,
        confirmed_location_id: candidate.id,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Location confirmation failed.');
    } finally {
      setLoading(false);
    }
  }

  async function reset() {
    if (sessionId) {
      try {
        await fetch('/api/advisor/reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId }),
        });
      } catch {
        // Local state must still be clearable if the server was restarted.
      }
    }
    localStorage.removeItem(SESSION_KEY);
    setSessionId('');
    setMessages([WELCOME]);
    setProfile({});
    setProgress({ completed: 0, total: 5, ready: false, checks: {}, missing: [] });
    setCandidates([]);
    onRecommendationsChange(null);
    setError('');
    onAnchorChange(null);
  }

  const needs = [
    profile.transport_importance === 'high' ? 'Transit priority' : null,
    profile.school_need === 'important' ? 'Schools' : null,
    profile.childcare_need === 'important' ? 'Childcare' : null,
    profile.healthcare_need === 'important' ? 'Healthcare' : null,
    profile.park_need === 'important' ? 'Parks' : null,
    ...(profile.additional_needs || []),
  ].filter(Boolean) as string[];

  return (
    <section className="advisor-section">
      <div className="advisor-heading">
        <div><p className="overline">CONVERSATIONAL HOUSING AGENT</p><h1>Start with a question.<br /><em>Discover the plan together.</em></h1></div>
        <p>The advisor answers first, then gradually turns your circumstances into explicit, reviewable housing preferences.</p>
      </div>

      <div className="advisor-shell">
        <div className="advisor-chat">
          <header className="advisor-chat__header">
            <div><span className="advisor-orb"><i /></span><p><b>HomeRadar Advisor</b><small>{available ? 'AI + verified project tools' : 'Deterministic local mode'}</small></p></div>
            <button type="button" onClick={reset}>Clear profile</button>
          </header>

          <div className="advisor-messages" aria-live="polite">
            {messages.map((message) => (
              <div className={`advisor-message advisor-message--${message.role}`} key={message.id}>
                <span>{message.role === 'assistant' ? 'HR' : 'You'}</span>
                <div>
                  <p>{message.content}</p>
                  {!!message.warnings?.length && message.warnings.map((warning) => <small className="advisor-warning" key={warning}>{warning}</small>)}
                  {!!message.sources?.length && (
                    <details className="advisor-sources">
                      <summary>{message.sources.length} evidence source{message.sources.length > 1 ? 's' : ''}</summary>
                      {message.sources.map((source) => source.url
                        ? <a key={`${source.title}-${source.url}`} href={source.url} target="_blank" rel="noreferrer"><i>{sourceLabel(source)}</i>{source.title}</a>
                        : <span key={source.title}><i>{sourceLabel(source)}</i>{source.title}</span>)}
                    </details>
                  )}
                </div>
              </div>
            ))}

            {candidates.length > 0 && (
              <div className="advisor-location-choices">
                <p><b>Confirm the intended place</b><small>Coordinates come from OneMap, not the language model.</small></p>
                {candidates.map((candidate) => (
                  <button type="button" key={candidate.id} disabled={loading} onClick={() => confirmLocation(candidate)}>
                    <span><b>{candidate.name}</b><small>{candidate.address}</small></span>
                    <em>{titleCase(candidate.subzone)} · {titleCase(candidate.planning_area)} →</em>
                  </button>
                ))}
              </div>
            )}

            {recommendations && <AdvisorRecommendationsView data={recommendations} profile={profile} onShowMap={onShowMap} />}
            {loading && <div className="advisor-typing"><i /><i /><i /><span>Checking your profile and evidence…</span></div>}
            <div ref={endRef} />
          </div>

          {!sessionId && messages.length === 1 && (
            <div className="advisor-prompts">
              {[
                '我是来新加坡读大学的学生，还不知道应该住哪里。',
                '第一次在新加坡买 HDB，我应该先考虑什么？',
                '我想租房，但不知道多少预算比较合理。',
              ].map((prompt) => <button type="button" key={prompt} onClick={() => send(undefined, prompt)}>{prompt}<span>→</span></button>)}
            </div>
          )}

          <form className="advisor-composer" onSubmit={send}>
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} maxLength={4000} placeholder="Ask a question or tell me something about your situation…" />
            <button disabled={loading || !draft.trim()} aria-label="Send message">↑</button>
          </form>
          {error && <p className="advisor-error">{error}</p>}
          <p className="advisor-privacy">{privacy}</p>
        </div>

        <aside className="advisor-profile">
          <div className="advisor-profile__head">
            <div><p className="overline">YOUR WORKING PROFILE</p><h2>What I understand</h2></div>
            <strong>{progress.completed}/{progress.total}</strong>
          </div>
          <div className="advisor-progress"><span style={{ width: `${progress.completed / progress.total * 100}%` }} /></div>
          <div className="advisor-profile__facts">
            <article className={progress.checks.housing_mode ? 'complete' : ''}><small>Plan</small><b>{profile.housing_mode ? titleCase(profile.housing_mode) : 'Not decided'}</b></article>
            <article className={progress.checks.location ? 'complete' : ''}><small>Location</small><b>{profile.anchor_name || profile.preferred_towns?.map(titleCase).join(', ') || profile.location_raw || profile.location_query || 'Not set'}</b>{locationStatus(profile) && <em>{locationStatus(profile)}</em>}</article>
            <article className={progress.checks.maximum_budget ? 'complete' : ''}><small>Maximum budget</small><b>{profileBudget(profile)}</b></article>
            <article className={progress.checks.rooms ? 'complete' : ''}><small>Rooms</small><b>{profileRooms(profile)}</b></article>
            <article className={progress.checks.extra_needs ? 'complete' : ''}><small>Extra needs</small><b>{needs.length ? needs.join(' · ') : profile.needs_discussed ? 'No strong extra need' : 'Not discussed'}</b></article>
          </div>
          {(profile.life_stage || profile.institution || profile.workplace) && (
            <div className="advisor-profile__context"><small>Life context</small><p>{[profile.life_stage, profile.institution, profile.workplace].filter(Boolean).join(' · ')}</p></div>
          )}
          <div className={`advisor-readiness ${progress.ready ? 'ready' : ''}`}>
            <i />
            <p><b>{progress.ready ? 'Ready for a grounded shortlist' : 'Still learning what matters'}</b><small>{progress.ready ? 'Ask for recommendations whenever you are ready.' : 'The advisor asks only one key follow-up at a time.'}</small></p>
          </div>
          <p className="advisor-profile__boundary">No diagnosis or protected characteristic is used for ranking. Route travel time and complete live-market coverage remain unavailable.</p>
        </aside>
      </div>
    </section>
  );
}

function AdvisorRecommendationsView({ data, profile, onShowMap }: { data: AdvisorRecommendations; profile: AdvisorProfile; onShowMap: (mode: 'sale' | 'rent', listingIds?: string[]) => void }) {
  const mapMode = data.mode === 'buy' ? 'sale' : 'rent';
  const listingIds = data.listings.map((listing) => listing.id);
  return (
    <div className="advisor-recommendations">
      <div className="advisor-recommendations__head">
        <div><p className="overline">AGENT SHORTLIST</p><h3>Three places, three real listings.</h3></div>
        {profile.anchor_latitude != null && <button type="button" onClick={() => onShowMap(mapMode, listingIds)}>View radius on map →</button>}
      </div>
      {!!data.warnings?.length && data.warnings.map((warning) => <p className="advisor-result-warning" key={warning}>{warning}</p>)}
      <p className="advisor-result-label">Recommended locations</p>
      <div className="advisor-area-grid">
        {data.areas.map((area, index) => (
          <article key={area.id}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <div><h4>{titleCase(area.name)}</h4><p>{titleCase(area.subzone || area.planning_area)}</p></div>
            <b>{money.format(area.typical_price)}<small>{area.price_unit}</small></b>
            {area.anchor_distance_m != null && <em>{(area.anchor_distance_m / 1000).toFixed(2)} km from anchor</em>}
            <p>{area.reasons?.[0]}</p>
          </article>
        ))}
      </div>
      <p className="advisor-result-label">Matching snapshot listings</p>
      <div className="advisor-listing-grid">
        {data.listings.map((listing) => (
          <article key={listing.id}>
            <div><span>{data.mode === 'rent' ? 'FOR RENT' : 'FOR SALE'}</span><b>{money.format(listing.price)}{data.mode === 'rent' && <small> / month</small>}</b></div>
            <h4>{listing.address || listing.title}</h4>
            <p>{titleCase(listing.subzone || listing.planning_area)}{listing.room_type ? ` · ${listing.room_type}` : ''}</p>
            <div className="advisor-listing-tags">
              {listing.anchor_distance_m != null && <span>{(listing.anchor_distance_m / 1000).toFixed(2)} km away</span>}
              {listing.nearest_mrt_distance_m != null && <span>{Math.round(listing.nearest_mrt_distance_m)} m to recorded MRT</span>}
              {listing.floor_area_sqft != null && <span>{Number(listing.floor_area_sqft).toLocaleString()} sqft</span>}
            </div>
            <button className="advisor-listing-map" type="button" onClick={() => onShowMap(mapMode, [listing.id])}>View map →</button>
            <details><summary>Why this match</summary><ul>{listing.reasons?.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>
          </article>
        ))}
      </div>
      {!data.listings.length && <div className="advisor-no-match">No real listing in the partial snapshot satisfies every hard condition. Nothing was silently relaxed.</div>}
      {data.disclaimer && <p className="advisor-result-disclaimer">{data.disclaimer}</p>}
    </div>
  );
}
