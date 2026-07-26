import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import type { LocationAnchor } from '../../lib/types';

const SESSION_KEY = 'sg-homeradar-general-agent-session';
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
  cards?: AgentCard[];
}

export interface AgentCard {
  kind: 'listing' | 'historical' | 'area';
  id: string;
  title: string;
  subtitle?: string | null;
  mode?: 'sale' | 'rent' | null;
  price?: number | null;
  price_unit?: string | null;
  planning_area?: string | null;
  subzone?: string | null;
  metrics?: Array<{ label: string; value: string }>;
  historical_windows?: HistoricalWindow[];
  model_reference?: ModelReference | null;
  reasons?: string[];
  latitude?: number | null;
  longitude?: number | null;
}

interface ModelReference {
  label: string;
  price?: number | null;
  vs_observed_percent?: number | null;
  role?: string | null;
  holdout_mape_percent?: number | null;
  training_end_month?: string | null;
}

interface HistoricalWindow {
  label: string;
  lookback_months: number;
  median_resale_price?: number | null;
  observed_price_low?: number | null;
  observed_price_high?: number | null;
  transaction_count: number;
  first_transaction_month?: string | null;
  last_transaction_month?: string | null;
  annual_trend_pct?: number | null;
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
  cards?: AgentCard[];
  sources: Source[];
  warnings?: string[];
  method?: string;
  privacy: string;
}

interface AdvisorStateResponse {
  session_id: string;
  profile: AdvisorProfile;
  progress: ProfileProgress;
  turns: Array<{
    role: 'user' | 'assistant';
    content: string;
    sources?: Source[];
    warnings?: string[];
    cards?: AgentCard[];
  }>;
  location_candidates: LocationCandidate[];
  privacy: string;
}

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我是 HomeRadar AI。你可以像使用 ChatGPT 一样直接问任何与新加坡租房、买房或区域选择有关的问题。我会为每个问题查询项目数据，再给你有依据的回答。\n\n你不需要先填写预算、地点或房型，也可以直接问“怎么使用这个软件？”或“现在有什么房子推荐？”。',
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

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const tokenPattern = /(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;

  for (const match of text.matchAll(tokenPattern)) {
    const index = match.index ?? 0;
    const token = match[0];
    const key = `${keyPrefix}-${index}`;
    if (index > cursor) nodes.push(text.slice(cursor, index));

    if (token.startsWith('**') && token.endsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      nodes.push(link
        ? <a key={key} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>
        : token);
    }
    cursor = index + token.length;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function MarkdownMessage({ content }: { content: string }) {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let listType: 'ul' | 'ol' | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const blockKey = `paragraph-${blocks.length}`;
    blocks.push(
      <p key={blockKey}>
        {paragraph.map((line, index) => (
          <span key={`${blockKey}-${index}`}>
            {index > 0 && <br />}
            {renderInlineMarkdown(line, `${blockKey}-${index}`)}
          </span>
        ))}
      </p>,
    );
    paragraph = [];
  };

  const flushList = () => {
    if (!listType || !listItems.length) return;
    const blockKey = `${listType}-${blocks.length}`;
    const items = listItems.map((item, index) => (
      <li key={`${blockKey}-${index}`}>
        {renderInlineMarkdown(item, `${blockKey}-${index}`)}
      </li>
    ));
    blocks.push(listType === 'ol'
      ? <ol key={blockKey}>{items}</ol>
      : <ul key={blockKey}>{items}</ul>);
    listItems = [];
    listType = null;
  };

  content.replace(/\r\n?/g, '\n').split('\n').forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const blockKey = `heading-${blocks.length}`;
      blocks.push(<h3 key={blockKey}>{renderInlineMarkdown(heading[1], blockKey)}</h3>);
      return;
    }

    const bullet = line.match(/^[-*+]\s+(.+)$/);
    const numbered = line.match(/^\d+[.)]\s+(.+)$/);
    if (bullet || numbered) {
      flushParagraph();
      const nextType = numbered ? 'ol' : 'ul';
      if (listType && listType !== nextType) flushList();
      listType = nextType;
      listItems.push((bullet || numbered)?.[1] || '');
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  return <div className="advisor-markdown">{blocks}</div>;
}

export function AdvisorView({
  available,
  variant = 'page',
  onClose,
  onAnchorChange,
  recommendations,
  onRecommendationsChange,
  onListingFocus,
}: {
  available: boolean;
  variant?: 'page' | 'widget';
  onClose?: () => void;
  onAnchorChange: (anchor: LocationAnchor | null) => void;
  recommendations: AdvisorRecommendations | null;
  onRecommendationsChange: (recommendations: AdvisorRecommendations | null) => void;
  onListingFocus?: (card: AgentCard, peerCards: AgentCard[]) => void;
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
    fetch(`/api/agent/session?session_id=${encodeURIComponent(sessionId)}`)
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
        cards: data.cards,
      },
    ]);
  }

  async function callAdvisor(body: Record<string, unknown>, retryExpired = true): Promise<AdvisorResponse> {
    const response = await fetch('/api/agent/message', {
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
        await fetch('/api/agent/reset', {
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
    <section className={`advisor-section advisor-section--${variant}`}>
      {variant === 'page' && (
        <div className="advisor-heading">
          <div><p className="overline">DATA-GROUNDED HOUSING AGENT</p><h1>Ask anything.<br /><em>Let the data answer.</em></h1></div>
          <p>A general Singapore housing AI that decides which project data to query for every turn. No questionnaire is required.</p>
        </div>
      )}

      <div className="advisor-shell">
        <div className="advisor-chat">
          <header className="advisor-chat__header">
            <div><span className="advisor-orb"><i /></span><p><b>HomeRadar Advisor</b><small>{available ? 'AI + verified project tools' : 'Deterministic local mode'}</small></p></div>
            <div className="advisor-chat__actions">
              <button type="button" onClick={reset}>Clear conversation</button>
              {variant === 'widget' && <button type="button" onClick={onClose} aria-label="Close advisor">Close</button>}
            </div>
          </header>

          <div className="advisor-messages" aria-live="polite">
            {messages.map((message) => (
              <div className={`advisor-message advisor-message--${message.role}`} key={message.id}>
                <span>{message.role === 'assistant' ? 'HR' : 'You'}</span>
                <div>
                  <MarkdownMessage content={message.content} />
                  {!!message.warnings?.length && message.warnings.map((warning) => <small className="advisor-warning" key={warning}>{warning}</small>)}
                  {!!message.sources?.length && (
                    <details className="advisor-sources">
                      <summary>{message.sources.length} evidence source{message.sources.length > 1 ? 's' : ''}</summary>
                      {message.sources.map((source) => source.url
                        ? <a key={`${source.title}-${source.url}`} href={source.url} target="_blank" rel="noreferrer"><i>{sourceLabel(source)}</i>{source.title}</a>
                        : <span key={source.title}><i>{sourceLabel(source)}</i>{source.title}</span>)}
                    </details>
                  )}
                  {!!message.cards?.length && (
                    <AgentEvidenceCards cards={message.cards} onListingFocus={onListingFocus} />
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

            {recommendations && <AdvisorRecommendationsView data={recommendations} profile={profile} />}
            {loading && <div className="advisor-typing"><i /><i /><i /><span>Querying project data and preparing an answer…</span></div>}
            <div ref={endRef} />
          </div>

          {!sessionId && messages.length === 1 && (
            <div className="advisor-prompts">
              {[
                '我怎么使用这个软件？',
                '现在有什么推荐的房子？',
                '比较一下榜鹅和淡滨尼适合什么样的人。',
              ].map((prompt) => <button type="button" key={prompt} onClick={() => send(undefined, prompt)}>{prompt}<span>→</span></button>)}
            </div>
          )}

          <form className="advisor-composer" onSubmit={send}>
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} maxLength={6000} placeholder="Ask anything about renting or buying in Singapore..." />
            <button disabled={loading || !draft.trim()} aria-label="Send message">&rarr;</button>
          </form>
          {error && <p className="advisor-error">{error}</p>}
          <p className="advisor-privacy">{privacy}</p>
        </div>

        <aside className="advisor-profile">
          <div className="advisor-profile__head">
            <div><p className="overline">OPTIONAL CONVERSATION MEMORY</p><h2>What I remember</h2></div>
            <strong>{progress.completed}</strong>
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
            <p><b>Context is optional</b><small>Ask any question now. These details only help later answers become more relevant.</small></p>
          </div>
          <p className="advisor-profile__boundary">Every housing claim is grounded in project data or an explicitly cited web source. Protected characteristics are never used for ranking.</p>
        </aside>
      </div>
    </section>
  );
}

function AgentEvidenceCards({ cards, onListingFocus }: { cards: AgentCard[]; onListingFocus?: (card: AgentCard, peerCards: AgentCard[]) => void }) {
  return (
    <div className="agent-evidence">
      <p className="agent-evidence__label">Database results</p>
      <div className="agent-evidence__grid">
        {cards.map((card) => {
          const canFocus = card.kind === 'listing' && card.latitude != null && card.longitude != null && onListingFocus;
          return (
          <article
            key={`${card.kind}:${card.id}`}
            className={canFocus ? 'agent-evidence__card--clickable' : undefined}
            role={canFocus ? 'button' : undefined}
            tabIndex={canFocus ? 0 : undefined}
            onClick={() => { if (canFocus) onListingFocus(card, cards); }}
            onKeyDown={(event) => {
              if (!canFocus) return;
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onListingFocus(card, cards);
              }
            }}
          >
            <div className="agent-evidence__top">
              <span>{card.kind === 'listing' ? card.mode === 'rent' ? 'FOR RENT' : 'FOR SALE' : card.kind === 'historical' ? 'HISTORICAL COMPARISON' : 'AREA'}</span>
              {card.price != null && !card.historical_windows?.length && <b>{money.format(card.price)}<small>{card.price_unit ? ` · ${card.price_unit}` : ''}</small></b>}
            </div>
            <h4>{card.title}</h4>
            <p>{card.subtitle || titleCase(card.subzone || card.planning_area)}</p>
            {!!card.historical_windows?.length && (
              <div className="agent-evidence__windows">
                {card.historical_windows.map((window) => (
                  <div key={`${card.id}-${window.lookback_months}`}>
                    <small>{window.label}</small>
                    <b>{window.median_resale_price != null ? money.format(window.median_resale_price) : 'No data'}</b>
                    <span>{window.transaction_count.toLocaleString()} transactions{window.first_transaction_month && window.last_transaction_month ? ` · ${window.first_transaction_month}–${window.last_transaction_month}` : ''}</span>
                    {window.observed_price_low != null && window.observed_price_high != null && (
                      <em>Middle 50%: {money.format(window.observed_price_low)}–{money.format(window.observed_price_high)}</em>
                    )}
                    {window.annual_trend_pct != null && (
                      <em>Town/type annual trend: {window.annual_trend_pct >= 0 ? '+' : ''}{window.annual_trend_pct.toFixed(1)}%</em>
                    )}
                  </div>
                ))}
              </div>
            )}
            {card.model_reference && (
              <div className="agent-evidence__model-reference">
                <small>{card.model_reference.label || 'Random forest reference'}</small>
                <b>{card.model_reference.price != null ? money.format(card.model_reference.price) : 'No model price'}</b>
                {card.model_reference.vs_observed_percent != null && (
                  <span>{card.model_reference.vs_observed_percent >= 0 ? '+' : ''}{card.model_reference.vs_observed_percent.toFixed(1)}% vs observed median</span>
                )}
                <em>{card.model_reference.role || 'reference estimate only'}{card.model_reference.holdout_mape_percent != null ? ` · holdout MAPE ${card.model_reference.holdout_mape_percent.toFixed(1)}%` : ''}</em>
              </div>
            )}
            {!!card.metrics?.length && (
              <div className="agent-evidence__metrics">
                {card.metrics.map((metric) => <span key={`${metric.label}:${metric.value}`}><small>{metric.label}</small><b>{metric.value}</b></span>)}
              </div>
            )}
            {!!card.reasons?.length && <details><summary>Evidence details</summary><ul>{card.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>}
          </article>
          );
        })}
      </div>
    </div>
  );
}

function AdvisorRecommendationsView({ data, profile }: { data: AdvisorRecommendations; profile: AdvisorProfile }) {
  return (
    <div className="advisor-recommendations">
      <div className="advisor-recommendations__head">
        <div><p className="overline">AGENT SHORTLIST</p><h3>Three places, three real listings.</h3></div>
        {profile.anchor_latitude != null && <span>Highlighted on the map</span>}
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
            <details><summary>Why this match</summary><ul>{listing.reasons?.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>
          </article>
        ))}
      </div>
      {!data.listings.length && <div className="advisor-no-match">No real listing in the partial snapshot satisfies every hard condition. Nothing was silently relaxed.</div>}
      {data.disclaimer && <p className="advisor-result-disclaimer">{data.disclaimer}</p>}
    </div>
  );
}
