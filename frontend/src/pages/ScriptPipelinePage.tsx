import React, { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Image,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  Upload,
  UploadFile,
  UploadProps,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FileImageOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  LeftOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RightOutlined,
  TeamOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  CharacterProfile,
  GeneratedScriptResponse,
  KeyframeAsset,
  PrepareCharactersResponse,
  ReferenceImageAsset,
  RenderClipResult,
  RenderStatusResponse,
  SceneProfile,
  SegmentDialogueItem,
  ScriptSummary,
  SegmentItem,
  SegmentKeyframes,
  SplitValidationReport,
  WorkflowMode,
  resolveAssetUrl,
  resolveDisplayAssetUrl,
  scriptPipelineApi,
} from '../services/api'
import { useProjectStore } from '../stores/project'

const { Title, Paragraph, Text } = Typography
const { TextArea } = Input

const WORKFLOW_MODE_STANDARD: WorkflowMode = 'standard'
const WORKFLOW_MODE_LONG_SHOT: WorkflowMode = 'long_shot'
const DEFAULT_STANDARD_PROVIDER = 'kling'
const DEFAULT_KLING_MODEL = 'kling-v3-omni'
const DEFAULT_DOUBAO_MODEL = 'doubao-seedance-1-5-pro-251215'

const getDefaultProviderForWorkflow = (workflowMode: WorkflowMode) =>
  workflowMode === WORKFLOW_MODE_STANDARD ? DEFAULT_STANDARD_PROVIDER : 'auto'

const getDefaultProviderModel = (provider: string) =>
  provider === 'doubao' ? DEFAULT_DOUBAO_MODEL : DEFAULT_KLING_MODEL

const buildStepItems = (workflowMode: WorkflowMode) => [
  { title: '输入需求', subtitle: '创意、角色、参考图', icon: <FileTextOutlined /> },
  { title: '确认剧本', subtitle: '确认内容并按约束分段', icon: <EditOutlined /> },
  { title: '审核片段', subtitle: '审核分段结果与画面描述', icon: <CheckCircleOutlined /> },
  workflowMode === WORKFLOW_MODE_LONG_SHOT
    ? { title: '审核首尾帧', subtitle: '确认关键帧连续性', icon: <FileImageOutlined /> }
    : { title: '审核首帧', subtitle: '确认各片段的内容重点', icon: <FileImageOutlined /> },
  { title: '渲染进度', subtitle: '查看片段生成与组装状态', icon: <VideoCameraOutlined /> },
  { title: '查看结果', subtitle: '成片与片段结果', icon: <EyeOutlined /> },
]

const statusColorMap: Record<string, string> = {
  queued: 'default',
  dispatching: 'processing',
  processing: 'processing',
  paused: 'orange',
  completed: 'success',
  failed: 'error',
  cancelled: 'orange',
}

const buildSummary = (generated?: GeneratedScriptResponse | null) => generated?.summary || null

const buildUploadFileList = (assets: ReferenceImageAsset[]): UploadFile[] =>
  assets.map((asset) => ({
    uid: asset.id,
    name: asset.original_filename || asset.filename,
    status: 'done',
    url: resolveAssetUrl(asset.url),
    thumbUrl: resolveDisplayAssetUrl(asset.url, asset.thumbnail_url),
  }))

const formatApiErrorDetail = (detail: unknown): string => {
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') {
          return item
        }
        if (item && typeof item === 'object') {
          const entry = item as { msg?: unknown; loc?: unknown }
          const loc = Array.isArray(entry.loc) ? entry.loc.join('.') : ''
          const msg = typeof entry.msg === 'string' ? entry.msg : ''
          return [loc, msg].filter(Boolean).join(': ')
        }
        return ''
      })
      .filter(Boolean)
    if (messages.length) {
      return messages.join(' | ')
    }
  }

  if (detail && typeof detail === 'object') {
    const entry = detail as { detail?: unknown; message?: unknown; msg?: unknown }
    if (typeof entry.message === 'string' && entry.message.trim()) {
      return entry.message
    }
    if (typeof entry.msg === 'string' && entry.msg.trim()) {
      return entry.msg
    }
    if (entry.detail !== undefined && entry.detail !== detail) {
      return formatApiErrorDetail(entry.detail)
    }
    try {
      return JSON.stringify(detail)
    } catch {
      return '请求失败'
    }
  }

  return ''
}

const extractApiErrorMessage = (error: unknown, fallback: string): string => {
  const responseError = error as { response?: { data?: { detail?: unknown; message?: unknown } } }
  const detailMessage = formatApiErrorDetail(responseError.response?.data?.detail)
  if (detailMessage) {
    return detailMessage
  }
  const messageText = responseError.response?.data?.message
  if (typeof messageText === 'string' && messageText.trim()) {
    return messageText
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return fallback
}

const MAX_SEGMENT_DURATION = 15

const normalizeWorkflowMode = (value: unknown): WorkflowMode =>
  value === WORKFLOW_MODE_LONG_SHOT ? WORKFLOW_MODE_LONG_SHOT : WORKFLOW_MODE_STANDARD

const inferWorkflowModeFromProjectState = (state: Record<string, unknown>, fallback?: unknown): WorkflowMode => {
  if ('workflowMode' in state) {
    return normalizeWorkflowMode(state.workflowMode)
  }
  const restoredKeyframes = Array.isArray(state.keyframes) ? state.keyframes : []
  if (restoredKeyframes.length > 0) {
    return WORKFLOW_MODE_LONG_SHOT
  }
  const currentStep = Number(state.currentStep ?? fallback ?? 0)
  if (Number.isFinite(currentStep) && currentStep >= 3) {
    return WORKFLOW_MODE_LONG_SHOT
  }
  return WORKFLOW_MODE_STANDARD
}

const clampSegmentDuration = (value: number): number => {
  if (!Number.isFinite(value)) {
    return 5
  }
  return Math.max(1, Math.min(MAX_SEGMENT_DURATION, value))
}

const looksLikeCharacterId = (value: string): boolean => /^[A-Za-z0-9][A-Za-z0-9_-]{5,}$/.test(value.trim())

const parseSegmentDialogueLine = (rawValue: unknown): SegmentDialogueItem | null => {
  if (rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)) {
    const item = rawValue as Record<string, unknown>
    const normalized: SegmentDialogueItem = {
      text: String(item.text || item.dialogue || '').trim(),
      speaker_name: String(item.speaker_name || item.speaker || '').trim(),
      speaker_character_id: String(item.speaker_character_id || item.character_id || '').trim(),
      emotion: String(item.emotion || '').trim(),
      tone: String(item.tone || '').trim(),
    }
    return normalized.text ? normalized : null
  }

  const rawText = String(rawValue || '').trim()
  if (!rawText) {
    return null
  }

  let speakerName = ''
  let speakerCharacterId = ''
  let emotion = ''
  let tone = ''
  let text = rawText
  let prefix = ''
  let content = ''

  for (const separator of ['：', ':']) {
    const index = rawText.indexOf(separator)
    if (index >= 0) {
      prefix = rawText.slice(0, index)
      content = rawText.slice(index + 1)
      break
    }
  }

  if (prefix) {
    const bracketValues = Array.from(prefix.matchAll(/\[([^\]]+)\]/g)).map((match) => match[1].trim())
    speakerName = prefix.replace(/\[[^\]]+\]/g, '').trim()
    text = content.trim()

    bracketValues.forEach((item) => {
      if (!speakerCharacterId && looksLikeCharacterId(item)) {
        speakerCharacterId = item
        return
      }
      const labels = item.split('/').map((part) => part.trim()).filter(Boolean)
      if (!emotion && labels[0]) {
        emotion = labels[0]
      }
      if (!tone && labels[1]) {
        tone = labels[1]
      }
    })
  }

  return {
    text: text || rawText,
    speaker_name: speakerName,
    speaker_character_id: speakerCharacterId,
    emotion,
    tone,
  }
}

const normalizeSegmentDialogues = (value: unknown): SegmentDialogueItem[] => {
  const iterable = Array.isArray(value) ? value : value === undefined || value === null ? [] : [value]
  const normalized: SegmentDialogueItem[] = []
  const seen = new Set<string>()

  iterable.forEach((item) => {
    const parsed = parseSegmentDialogueLine(item)
    if (!parsed?.text) {
      return
    }
    const fingerprint = [
      parsed.text,
      parsed.speaker_name || '',
      parsed.speaker_character_id || '',
      parsed.emotion || '',
      parsed.tone || '',
    ].join('||')
    if (seen.has(fingerprint)) {
      return
    }
    seen.add(fingerprint)
    normalized.push(parsed)
  })

  return normalized
}

const formatSegmentDialogueLine = (dialogue: SegmentDialogueItem): string => {
  const text = String(dialogue.text || '').trim()
  const speakerName = String(dialogue.speaker_name || '').trim()
  const speakerCharacterId = String(dialogue.speaker_character_id || '').trim()
  const labels = [dialogue.emotion, dialogue.tone].map((item) => String(item || '').trim()).filter(Boolean)

  let prefix = speakerName
  if (speakerCharacterId) {
    prefix = `${prefix} [${speakerCharacterId}]`.trim()
  }
  if (labels.length) {
    prefix = `${prefix} [${labels.join(' / ')}]`.trim()
  }

  if (prefix && text) {
    return `${prefix}: ${text}`
  }
  return text || prefix
}

const formatSegmentDialoguesText = (dialogues: SegmentDialogueItem[]): string =>
  normalizeSegmentDialogues(dialogues)
    .map((item) => formatSegmentDialogueLine(item))
    .join('\n')

const normalizeSegmentGenerationConfig = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {}

const getSegmentGenerationConfig = (segment: SegmentItem): Record<string, unknown> =>
  normalizeSegmentGenerationConfig(segment.generation_config)

const isSegmentMultiShotEnabled = (segment: SegmentItem): boolean =>
  Boolean(getSegmentGenerationConfig(segment).kling_multi_shot_enabled)

const getSegmentMultiShotPrompts = (segment: SegmentItem): string[] => {
  const generationConfig = getSegmentGenerationConfig(segment)
  const rawItems = generationConfig.kling_multi_prompt
  if (!Array.isArray(rawItems)) {
    return []
  }

  return rawItems
    .map((item) => {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        return String((item as { prompt?: unknown }).prompt || '').trim()
      }
      return String(item || '').trim()
    })
    .filter(Boolean)
}

const formatMultiShotPromptsText = (prompts: string[]): string => prompts.map((item) => item.trim()).filter(Boolean).join('\n')

const parseMultiShotPromptsText = (value: string): string[] =>
  value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)

const buildVideoPromptSummaryFromMultiShot = (prompts: string[]): string =>
  prompts
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 3)
    .join('；')

const buildMultiShotPatch = (segment: SegmentItem, enabled: boolean, prompts?: string[]): Partial<SegmentItem> => {
  const generationConfig = getSegmentGenerationConfig(segment)
  const normalizedPrompts = (prompts || []).map((item) => item.trim()).filter(Boolean)

  if (!enabled) {
    const nextGenerationConfig = { ...generationConfig }
    delete nextGenerationConfig.kling_shot_type
    delete nextGenerationConfig.kling_multi_prompt
    return {
      generation_config: {
        ...nextGenerationConfig,
        kling_multi_shot_enabled: false,
        kling_multi_shot_reason: String(generationConfig.kling_multi_shot_reason || '已手动切换为单镜头模式'),
        kling_multi_shot_source: 'manual-edit',
      },
    }
  }

  const nextPrompts = normalizedPrompts.length
    ? normalizedPrompts
    : [segment.video_prompt.trim()].filter(Boolean)

  return {
    video_prompt: buildVideoPromptSummaryFromMultiShot(nextPrompts),
    generation_config: {
      ...generationConfig,
      kling_multi_shot_enabled: true,
      kling_shot_type: 'customize',
      kling_multi_prompt: nextPrompts,
      kling_multi_shot_reason: String(generationConfig.kling_multi_shot_reason || '已手动切换为多镜头模式'),
      kling_multi_shot_source: 'manual-edit',
    },
  }
}

const normalizeSegmentItem = (segment: SegmentItem): SegmentItem => ({
  ...segment,
  duration: clampSegmentDuration(Number(segment.duration)),
  key_dialogues: normalizeSegmentDialogues(segment.key_dialogues),
  generation_config: normalizeSegmentGenerationConfig(segment.generation_config),
  contains_primary_character: Boolean(segment.contains_primary_character),
  ending_contains_primary_character: Boolean(segment.ending_contains_primary_character),
  pre_generate_start_frame: Boolean(segment.pre_generate_start_frame),
  start_frame_generation_reason: String(segment.start_frame_generation_reason || ''),
  prefer_primary_character_end_frame: Boolean(segment.prefer_primary_character_end_frame),
  new_character_profile_ids: Array.isArray(segment.new_character_profile_ids) ? segment.new_character_profile_ids : [],
  handoff_character_profile_ids: Array.isArray(segment.handoff_character_profile_ids) ? segment.handoff_character_profile_ids : [],
  ending_contains_handoff_characters: Boolean(segment.ending_contains_handoff_characters),
  prefer_character_handoff_end_frame: Boolean(segment.prefer_character_handoff_end_frame),
})

const normalizeSegmentItems = (items: SegmentItem[]): SegmentItem[] => items.map(normalizeSegmentItem)

const normalizeMaxSegmentDuration = (value: number): number => {
  if (!Number.isFinite(value)) {
    return MAX_SEGMENT_DURATION
  }
  return Math.max(3, Math.min(MAX_SEGMENT_DURATION, value))
}

const findCharacterFirstFrameReference = (
  profileId: string,
  segments: SegmentItem[],
  keyframes: SegmentKeyframes[],
): KeyframeAsset | null => {
  const normalizedProfileId = String(profileId || '').trim()
  if (!normalizedProfileId) {
    return null
  }

  const keyframeMap = new Map(keyframes.map((bundle) => [Number(bundle.segment_number), bundle]))
  const sortedSegments = [...segments].sort((left, right) => left.segment_number - right.segment_number)

  for (const segment of sortedSegments) {
    if (!(segment.character_profile_ids || []).includes(normalizedProfileId)) {
      continue
    }
    const startFrame = keyframeMap.get(Number(segment.segment_number))?.start_frame
    if (startFrame?.asset_url) {
      return startFrame
    }
  }

  return null
}

const validationStatusToAlertType = (
  status?: string,
): 'success' | 'info' | 'warning' | 'error' => {
  if (status === 'fail') {
    return 'error'
  }
  if (status === 'warning') {
    return 'warning'
  }
  return 'success'
}

const validationStatusToTagColor = (status?: string): string => {
  if (status === 'fail') {
    return 'error'
  }
  if (status === 'warning') {
    return 'warning'
  }
  return 'success'
}

const hasMeaningfulProjectState = (state: {
  userInput: string
  projectTitle: string
  constraintCharacterIds: string[]
  constraintSceneIds: string[]
  selectedCharacterIds: string[]
  selectedSceneIds: string[]
  referenceImages: ReferenceImageAsset[]
  scriptDraft: string
  segments: SegmentItem[]
  keyframes: SegmentKeyframes[]
  renderTaskId: string | null
  currentStep: number
}) =>
  Boolean(
    state.userInput.trim() ||
      state.scriptDraft.trim() ||
      state.constraintCharacterIds.length ||
      state.constraintSceneIds.length ||
      state.selectedCharacterIds.length ||
      state.selectedSceneIds.length ||
      state.referenceImages.length ||
      state.segments.length ||
      state.keyframes.length ||
      state.renderTaskId ||
      state.currentStep > 0 ||
      state.projectTitle !== '未命名项目',
  )

const PreviewAsset: React.FC<{
  assetUrl?: string
  thumbnailUrl?: string
  assetType?: string
  title: string
}> = ({ assetUrl, thumbnailUrl, assetType, title }) => {
  const resolvedUrl = resolveAssetUrl(assetUrl)
  const displayUrl = resolveDisplayAssetUrl(assetUrl, thumbnailUrl)

  if (!resolvedUrl) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="结果未生成" />
  }

  if (assetType?.startsWith('image/')) {
    return (
      <Image
        alt={title}
        src={displayUrl}
        style={{ width: '100%', borderRadius: 12, objectFit: 'cover' }}
        preview={{ src: resolvedUrl, mask: '预览' }}
      />
    )
  }

  return <video controls src={resolvedUrl} style={{ width: '100%', borderRadius: 12, background: '#000' }} />
}

const downloadAsset = (assetUrl?: string, filename?: string) => {
  const resolvedUrl = resolveAssetUrl(assetUrl)
  if (!resolvedUrl) {
    message.warning('当前资源还不可下载')
    return
  }

  const link = document.createElement('a')
  link.href = resolvedUrl
  if (filename) {
    link.download = filename
  }
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

const isGatewayTimeoutError = (error: unknown): boolean => {
  const responseError = error as { response?: { status?: number } }
  return responseError.response?.status === 504
}

const readRequestedProjectId = (state: unknown): string | null => {
  if (!state || typeof state !== 'object') {
    return null
  }
  const projectId = (state as { projectId?: unknown }).projectId
  if (typeof projectId !== 'string') {
    return null
  }
  const normalized = projectId.trim()
  return normalized || null
}

const stableSerialize = (value: unknown): string => {
  if (value === null || value === undefined) {
    return 'null'
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(',')}]`
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right))
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`).join(',')}}`
  }
  return JSON.stringify(value)
}

export const ScriptPipelinePage: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const flowTrackRef = useRef<HTMLDivElement | null>(null)
  const stepButtonRefs = useRef<Array<HTMLButtonElement | null>>([])
  const suppressProjectSaveRef = useRef(true)
  const creatingProjectRef = useRef(false)
  const splitRequestInFlightRef = useRef(false)
  const keyframeRequestInFlightRef = useRef(false)
  const pendingRequestedProjectIdRef = useRef<string | null>(readRequestedProjectId(location.state))
  const selectedProjectId = useProjectStore((state) => state.currentProjectId)
  const projectStoreHydrated = useProjectStore((state) => state.hydrated)
  const setCurrentProjectId = useProjectStore((state) => state.setCurrentProjectId)
  const clearCurrentProjectId = useProjectStore((state) => state.clearCurrentProjectId)

  const [currentStep, setCurrentStep] = useState(0)
  const [transitionDirection, setTransitionDirection] = useState<'forward' | 'backward'>('forward')
  const [workflowMode, setWorkflowMode] = useState<WorkflowMode>(WORKFLOW_MODE_STANDARD)
  const [userInput, setUserInput] = useState('')
  const [stylePreference, setStylePreference] = useState('写实战术电影感')
  const [projectTitle, setProjectTitle] = useState('未命名项目')
  const [maxSegmentDuration, setMaxSegmentDuration] = useState<number>(MAX_SEGMENT_DURATION)
  const [targetTotalDuration, setTargetTotalDuration] = useState<number | null>(null)
  const [provider, setProvider] = useState(getDefaultProviderForWorkflow(WORKFLOW_MODE_STANDARD))
  const [resolution, setResolution] = useState('720p')
  const [aspectRatio, setAspectRatio] = useState('16:9')
  const [watermark, setWatermark] = useState(false)
  const [providerModel, setProviderModel] = useState(DEFAULT_KLING_MODEL)
  const [cameraFixed, setCameraFixed] = useState(false)
  const [generateAudio, setGenerateAudio] = useState(true)
  const [returnLastFrame, setReturnLastFrame] = useState(false)
  const [serviceTier, setServiceTier] = useState('default')
  const [seedInput, setSeedInput] = useState<number | null>(null)

  const [referenceImages, setReferenceImages] = useState<ReferenceImageAsset[]>([])
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([])
  const [characterProfiles, setCharacterProfiles] = useState<CharacterProfile[]>([])
  const [constraintCharacterIds, setConstraintCharacterIds] = useState<string[]>([])
  const [selectedCharacterIds, setSelectedCharacterIds] = useState<string[]>([])
  const [sceneProfiles, setSceneProfiles] = useState<SceneProfile[]>([])
  const [constraintSceneIds, setConstraintSceneIds] = useState<string[]>([])
  const [selectedSceneIds, setSelectedSceneIds] = useState<string[]>([])

  const [scriptLoading, setScriptLoading] = useState(false)
  const [splitLoading, setSplitLoading] = useState(false)
  const [splitReviewLoading, setSplitReviewLoading] = useState(false)
  const [keyframeLoading, setKeyframeLoading] = useState(false)
  const [keyframeRegeneratingSegmentNumber, setKeyframeRegeneratingSegmentNumber] = useState<number | null>(null)
  const [renderStarting, setRenderStarting] = useState(false)
  const [renderActionLoading, setRenderActionLoading] = useState(false)
  const [charactersLoading, setCharactersLoading] = useState(false)
  const [scenesLoading, setScenesLoading] = useState(false)

  const [error, setError] = useState<string | null>(null)

  const [generatedScript, setGeneratedScript] = useState<GeneratedScriptResponse | null>(null)
  const [manualCharacterProfiles, setManualCharacterProfiles] = useState<CharacterProfile[]>([])
  const [characterPrepareResult, setCharacterPrepareResult] = useState<PrepareCharactersResponse | null>(null)
  const [characterConfirmOpen, setCharacterConfirmOpen] = useState(false)
  const [characterConfirmMode, setCharacterConfirmMode] = useState<'generate_script' | 'split_script'>('generate_script')
  const [preparingCharacters, setPreparingCharacters] = useState(false)
  const [confirmedLibraryCharacterIds, setConfirmedLibraryCharacterIds] = useState<string[]>([])
  const [confirmedTemporaryCharacterIds, setConfirmedTemporaryCharacterIds] = useState<string[]>([])
  const [scriptDraft, setScriptDraft] = useState('')
  const [scriptSummary, setScriptSummary] = useState<ScriptSummary | null>(null)
  const [segments, setSegments] = useState<SegmentItem[]>([])
  const [splitValidationReport, setSplitValidationReport] = useState<SplitValidationReport | null>(null)
  const [keyframes, setKeyframes] = useState<SegmentKeyframes[]>([])
  const [renderTaskId, setRenderTaskId] = useState<string | null>(null)
  const [renderStatus, setRenderStatus] = useState<RenderStatusResponse | null>(null)
  const [projectHydrating, setProjectHydrating] = useState(true)
  const [savingTemporaryCharacterIds, setSavingTemporaryCharacterIds] = useState<string[]>([])
  const [savedTemporaryCharacterIds, setSavedTemporaryCharacterIds] = useState<string[]>([])

  const resetLocalState = () => {
    setCurrentStep(0)
    setTransitionDirection('forward')
    setWorkflowMode(WORKFLOW_MODE_STANDARD)
    setUserInput('')
    setStylePreference('写实战术电影感')
    setProjectTitle('未命名项目')
    setMaxSegmentDuration(MAX_SEGMENT_DURATION)
    setTargetTotalDuration(null)
    setProvider(getDefaultProviderForWorkflow(WORKFLOW_MODE_STANDARD))
    setResolution('720p')
    setAspectRatio('16:9')
    setWatermark(false)
    setProviderModel(DEFAULT_KLING_MODEL)
    setCameraFixed(false)
    setGenerateAudio(true)
    setReturnLastFrame(false)
    setServiceTier('default')
    setSeedInput(null)
    setReferenceImages([])
    setUploadFileList([])
    setConstraintCharacterIds([])
    setSelectedCharacterIds([])
    setConstraintSceneIds([])
    setSelectedSceneIds([])
    setGeneratedScript(null)
    setManualCharacterProfiles([])
    setCharacterPrepareResult(null)
    setCharacterConfirmOpen(false)
    setPreparingCharacters(false)
    setConfirmedLibraryCharacterIds([])
    setConfirmedTemporaryCharacterIds([])
    setScriptDraft('')
    setScriptSummary(null)
    setSegments([])
    setSplitValidationReport(null)
    setSplitReviewLoading(false)
    setKeyframes([])
    setKeyframeRegeneratingSegmentNumber(null)
    setRenderTaskId(null)
    setRenderStatus(null)
    setRenderActionLoading(false)
    setSavingTemporaryCharacterIds([])
    setSavedTemporaryCharacterIds([])
    setError(null)
  }

  const applyProjectState = (item: Record<string, unknown>) => {
    const state = (item.state as Record<string, unknown>) || {}
    const restoredReferenceImages = Array.isArray(state.referenceImages)
      ? (state.referenceImages as ReferenceImageAsset[])
      : []
    const restoredWorkflowMode = inferWorkflowModeFromProjectState(state, item.current_step)
    const restoredGeneratedScript =
      state.generatedScript && typeof state.generatedScript === 'object'
        ? (state.generatedScript as GeneratedScriptResponse)
        : null
    const restoredScriptSummary =
      state.scriptSummary && typeof state.scriptSummary === 'object'
        ? (state.scriptSummary as ScriptSummary)
        : null
    const restoredSegments = Array.isArray(state.segments)
      ? normalizeSegmentItems(state.segments as SegmentItem[])
      : []
    const restoredSplitValidationReport =
      state.splitValidationReport && typeof state.splitValidationReport === 'object'
        ? (state.splitValidationReport as SplitValidationReport)
        : null
    const restoredKeyframes = Array.isArray(state.keyframes) ? (state.keyframes as SegmentKeyframes[]) : []
    const restoredRenderStatus =
      state.renderStatus && typeof state.renderStatus === 'object'
        ? (state.renderStatus as RenderStatusResponse)
        : null

    setCurrentStep(Number(state.currentStep ?? item.current_step ?? 0))
    setTransitionDirection(state.transitionDirection === 'backward' ? 'backward' : 'forward')
    setWorkflowMode(restoredWorkflowMode)
    setUserInput(String(state.userInput || ''))
    setStylePreference(String(state.stylePreference || '写实战术电影感'))
    setProjectTitle(String(state.projectTitle || item.project_title || '未命名项目'))
    setMaxSegmentDuration(normalizeMaxSegmentDuration(Number(state.maxSegmentDuration || MAX_SEGMENT_DURATION)))
    setTargetTotalDuration(
      state.targetTotalDuration === null || state.targetTotalDuration === undefined
        ? null
        : Number(state.targetTotalDuration),
    )
    setProvider(String(state.provider || getDefaultProviderForWorkflow(restoredWorkflowMode)))
    setResolution(String(state.resolution || '720p'))
    setAspectRatio(String(state.aspectRatio || '16:9'))
    setWatermark(Boolean(state.watermark))
    setProviderModel(
      String(state.providerModel || getDefaultProviderModel(String(state.provider || getDefaultProviderForWorkflow(restoredWorkflowMode)))),
    )
    setCameraFixed(Boolean(state.cameraFixed))
    setGenerateAudio(state.generateAudio === false ? false : true)
    setReturnLastFrame(restoredWorkflowMode === WORKFLOW_MODE_LONG_SHOT && Boolean(state.returnLastFrame))
    setServiceTier(String(state.serviceTier || 'default'))
    setSeedInput(
      state.seedInput === null || state.seedInput === undefined || state.seedInput === ''
        ? null
        : Number(state.seedInput),
    )
    setReferenceImages(restoredReferenceImages)
    setUploadFileList(buildUploadFileList(restoredReferenceImages))
    setConstraintCharacterIds(
      Array.isArray(state.constraintCharacterIds) ? (state.constraintCharacterIds as string[]) : [],
    )
    setSelectedCharacterIds(
      Array.isArray(state.selectedCharacterIds) ? (state.selectedCharacterIds as string[]) : [],
    )
    setConstraintSceneIds(Array.isArray(state.constraintSceneIds) ? (state.constraintSceneIds as string[]) : [])
    setSelectedSceneIds(Array.isArray(state.selectedSceneIds) ? (state.selectedSceneIds as string[]) : [])
    setGeneratedScript(restoredGeneratedScript)
    setManualCharacterProfiles(
      Array.isArray(state.manualCharacterProfiles) ? (state.manualCharacterProfiles as CharacterProfile[]) : [],
    )
    setSavedTemporaryCharacterIds(
      Array.isArray(state.savedTemporaryCharacterIds) ? (state.savedTemporaryCharacterIds as string[]) : [],
    )
    setScriptDraft(String(state.scriptDraft || ''))
    setScriptSummary(restoredScriptSummary)
    setSegments(restoredSegments)
    setSplitValidationReport(restoredSplitValidationReport)
    setSplitReviewLoading(false)
    setKeyframes(restoredKeyframes)
    setKeyframeRegeneratingSegmentNumber(null)
    setRenderTaskId(
      typeof state.renderTaskId === 'string' && state.renderTaskId
        ? state.renderTaskId
        : String(item.last_render_task_id || '') || null,
    )
    setRenderStatus(restoredRenderStatus)
  }

  const buildProjectStateSnapshot = (overrides: Record<string, unknown> = {}) => ({
    currentStep,
    transitionDirection,
    workflowMode,
    userInput,
    stylePreference,
    projectTitle,
    maxSegmentDuration,
    targetTotalDuration,
    provider,
    resolution,
    aspectRatio,
    watermark,
    providerModel,
    cameraFixed,
    generateAudio,
    returnLastFrame,
    serviceTier,
    seedInput,
    referenceImages,
    constraintCharacterIds,
    constraintSceneIds,
    selectedCharacterIds,
    selectedSceneIds,
    generatedScript,
    manualCharacterProfiles,
    savedTemporaryCharacterIds,
    scriptDraft,
    scriptSummary,
    segments,
    splitValidationReport,
    keyframes,
    renderTaskId,
    renderStatus,
    ...overrides,
  })

  const buildProjectPayload = (overrides: {
    project_title?: string
    current_step?: number
    state?: Record<string, unknown>
    status?: string
    summary?: string
    last_render_task_id?: string
  } = {}) => ({
    project_title: overrides.project_title ?? (projectTitle.trim() || '未命名项目'),
    current_step: overrides.current_step ?? currentStep,
    state: overrides.state ?? buildProjectStateSnapshot(),
    status:
      overrides.status ??
      (renderStatus?.status === 'queued' || renderStatus?.status === 'dispatching' || renderStatus?.status === 'processing'
        ? 'in_progress'
        : renderStatus?.status === 'paused'
          ? 'paused'
          : renderStatus?.status === 'completed'
            ? 'completed'
            : renderStatus?.status === 'failed'
              ? 'failed'
              : renderStatus?.status === 'cancelled'
                ? 'cancelled'
                : renderTaskId
                  ? 'in_progress'
                  : (overrides.current_step ?? currentStep) >= 5
                    ? 'completed'
                    : 'draft'),
    last_render_task_id: overrides.last_render_task_id ?? (renderTaskId || undefined),
    summary: overrides.summary ?? (scriptSummary?.synopsis || ''),
  })

  const ensureProjectExists = async () => {
    if (selectedProjectId) {
      return selectedProjectId
    }

    const response = await scriptPipelineApi.createProject(
      buildProjectPayload({
        current_step: currentStep,
        state: buildProjectStateSnapshot(),
      }),
    )
    const projectId = response.data.item.id
    setCurrentProjectId(projectId)
    return projectId
  }

  const recoverGeneratedScriptFromProject = async (projectId: string, originalError: unknown) => {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
      try {
        const response = await scriptPipelineApi.getProject(projectId)
        const item = response.data.item as Record<string, unknown> | null
        const state = (item?.state as Record<string, unknown>) || {}
        if (item && (state.generatedScript || (typeof state.scriptDraft === 'string' && state.scriptDraft.trim()))) {
          applyProjectState(item)
          setCharacterPrepareResult(null)
          setCharacterConfirmOpen(false)
          setSavedTemporaryCharacterIds([])
          setError(null)
          message.warning('生成剧本请求超时，但后端已完成生成，已自动恢复到剧本确认阶段')
          return true
        }
      } catch {
        // Ignore polling errors and keep retrying until timeout.
      }
    }

    throw originalError
  }

  const recoverSplitScriptFromProject = async (
    projectId: string,
    requestMeta: {
      scriptText: string
      maxSegmentDuration: number
      targetTotalDuration: number | null
      workflowMode: WorkflowMode
    },
    originalError: unknown,
  ) => {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
      try {
        const response = await scriptPipelineApi.getProject(projectId)
        const item = response.data.item as Record<string, unknown> | null
        const state = (item?.state as Record<string, unknown>) || {}
        const restoredSegments = Array.isArray(state.segments) ? (state.segments as SegmentItem[]) : []
        const savedScriptDraft = String(state.scriptDraft || '').trim()
        const savedMaxSegmentDuration = normalizeMaxSegmentDuration(
          Number(state.maxSegmentDuration || MAX_SEGMENT_DURATION),
        )
        const savedTargetTotalDuration =
          state.targetTotalDuration === null || state.targetTotalDuration === undefined
            ? null
            : Number(state.targetTotalDuration)
        const savedWorkflowMode = inferWorkflowModeFromProjectState(state, item?.current_step)

        if (
          item &&
          restoredSegments.length > 0 &&
          savedScriptDraft === requestMeta.scriptText &&
          savedMaxSegmentDuration === requestMeta.maxSegmentDuration &&
          savedTargetTotalDuration === requestMeta.targetTotalDuration &&
          savedWorkflowMode === requestMeta.workflowMode
        ) {
          applyProjectState(item)
          setCharacterPrepareResult(null)
          setCharacterConfirmOpen(false)
          setError(null)
          message.warning('拆分片段请求超时，但后端已完成拆分，已自动恢复到片段确认阶段')
          return true
        }
      } catch {
        // Ignore polling errors and keep retrying until timeout.
      }
    }

    throw originalError
  }

  const recoverKeyframesFromProject = async (
    projectId: string,
    requestMeta: {
      style: string
      selectedCharacterIds: string[]
      selectedSceneIds: string[]
      referenceImages: ReferenceImageAsset[]
      segments: SegmentItem[]
      workflowMode: WorkflowMode
    },
    originalError: unknown,
  ) => {
    const expectedSegments = stableSerialize(requestMeta.segments)
    const expectedCharacterIds = stableSerialize(requestMeta.selectedCharacterIds)
    const expectedSceneIds = stableSerialize(requestMeta.selectedSceneIds)
    const expectedReferenceImages = stableSerialize(requestMeta.referenceImages)

    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
      try {
        const response = await scriptPipelineApi.getProject(projectId)
        const item = response.data.item as Record<string, unknown> | null
        const state = (item?.state as Record<string, unknown>) || {}
        const restoredKeyframes = Array.isArray(state.keyframes) ? (state.keyframes as SegmentKeyframes[]) : []
        const restoredSegments = Array.isArray(state.segments) ? normalizeSegmentItems(state.segments as SegmentItem[]) : []
        const restoredStyle = String(state.stylePreference || '').trim()
        const restoredCharacterIds = Array.isArray(state.selectedCharacterIds)
          ? (state.selectedCharacterIds as string[])
          : []
        const restoredSceneIds = Array.isArray(state.selectedSceneIds) ? (state.selectedSceneIds as string[]) : []
        const restoredReferenceImages = Array.isArray(state.referenceImages)
          ? (state.referenceImages as ReferenceImageAsset[])
          : []
        const restoredWorkflowMode = inferWorkflowModeFromProjectState(state, item?.current_step)

        if (
          item &&
          restoredKeyframes.length > 0 &&
          restoredKeyframes.length === requestMeta.segments.length &&
          restoredStyle === requestMeta.style &&
          restoredWorkflowMode === requestMeta.workflowMode &&
          stableSerialize(restoredSegments) === expectedSegments &&
          stableSerialize(restoredCharacterIds) === expectedCharacterIds &&
          stableSerialize(restoredSceneIds) === expectedSceneIds &&
          stableSerialize(restoredReferenceImages) === expectedReferenceImages
        ) {
          applyProjectState(item)
          setError(null)
          message.warning('首帧生成请求超时，但后端已完成生成，已自动恢复到首尾帧审核阶段')
          return true
        }
      } catch {
        // Ignore polling errors and keep retrying until timeout.
      }
    }

    throw originalError
  }

  useEffect(() => {
    const fetchCharacters = async () => {
      setCharactersLoading(true)
      try {
        const response = await scriptPipelineApi.listCharacters()
        setCharacterProfiles(response.data.items || [])
      } catch {
        message.error('角色档案加载失败')
      } finally {
        setCharactersLoading(false)
      }
    }

    fetchCharacters()
  }, [])

  useEffect(() => {
    const fetchScenes = async () => {
      setScenesLoading(true)
      try {
        const response = await scriptPipelineApi.listScenes()
        setSceneProfiles(response.data.items || [])
      } catch {
        message.error('场景档案加载失败')
      } finally {
        setScenesLoading(false)
      }
    }

    fetchScenes()
  }, [])

  useEffect(() => {
    pendingRequestedProjectIdRef.current = readRequestedProjectId(location.state)
  }, [location.key, location.state])

  useEffect(() => {
    if (workflowMode === WORKFLOW_MODE_LONG_SHOT) {
      setReturnLastFrame(true)
      return
    }
    setReturnLastFrame(false)
  }, [workflowMode])

  useEffect(() => {
    if (!projectStoreHydrated) {
      return
    }

    let active = true

    const restoreProject = async () => {
      setProjectHydrating(true)
      try {
        let item: Record<string, unknown> | null = null
        const requestedProjectId = pendingRequestedProjectIdRef.current || selectedProjectId
        const hasExplicitRequestedProject = Boolean(pendingRequestedProjectIdRef.current)

        if (requestedProjectId) {
          try {
            const response = await scriptPipelineApi.getProject(requestedProjectId)
            item = response.data.item as Record<string, unknown> | null
            if (item?.id) {
              setCurrentProjectId(String(item.id))
            }
          } catch {
            if (hasExplicitRequestedProject || requestedProjectId === selectedProjectId) {
              clearCurrentProjectId()
            }
          }
        }

        if (!item) {
          if (hasExplicitRequestedProject) {
            if (active) {
              resetLocalState()
            }
            return
          }
          const response = await scriptPipelineApi.getCurrentProject()
          item = response.data.item as Record<string, unknown> | null
          if (item?.id) {
            setCurrentProjectId(String(item.id))
          }
        }

        if (!active) {
          return
        }
        if (!item?.state) {
          resetLocalState()
          return
        }
        applyProjectState(item)
      } catch {
        message.error('恢复当前项目失败')
      } finally {
        if (active) {
          pendingRequestedProjectIdRef.current = null
          setProjectHydrating(false)
          suppressProjectSaveRef.current = false
        }
      }
    }

    restoreProject()

    return () => {
      active = false
    }
  }, [clearCurrentProjectId, projectStoreHydrated, selectedProjectId, setCurrentProjectId])

  useEffect(() => {
    if (!renderTaskId) {
      return
    }

    if (renderStatus?.status && ['completed', 'failed', 'cancelled', 'paused'].includes(renderStatus.status)) {
      return
    }

    let active = true
    let timer: number | undefined

    const fetchStatus = async () => {
      try {
        const response = await scriptPipelineApi.getRenderStatus(renderTaskId)
        if (!active) {
          return
        }

        setRenderStatus(response.data)

        if (response.data.status === 'completed') {
          setCurrentStep(5)
          return
        }

        if (response.data.status === 'failed') {
          setError(response.data.error || '渲染失败')
          return
        }

        if (response.data.status === 'cancelled') {
          return
        }

        timer = window.setTimeout(fetchStatus, 1500)
    } catch (pollError: unknown) {
      if (!active) {
        return
      }
      setError(extractApiErrorMessage(pollError, '查询渲染状态失败'))
    }
    }

    fetchStatus()

    return () => {
      active = false
      if (timer) {
        window.clearTimeout(timer)
      }
    }
  }, [renderTaskId, renderStatus?.status])

  useEffect(() => {
    const track = flowTrackRef.current
    const activeButton = stepButtonRefs.current[currentStep]
    if (!track || !activeButton) {
      return
    }

    const targetLeft =
      activeButton.offsetLeft - track.clientWidth / 2 + activeButton.clientWidth / 2

    track.scrollTo({
      left: Math.max(0, targetLeft),
      behavior: 'smooth',
    })
  }, [currentStep])

  useEffect(() => {
    if (projectHydrating || suppressProjectSaveRef.current) {
      return
    }

    const stateForSave = buildProjectStateSnapshot()

    if (
      !hasMeaningfulProjectState({
        userInput,
        projectTitle,
        constraintCharacterIds,
        constraintSceneIds,
        selectedCharacterIds,
        selectedSceneIds,
        referenceImages,
        scriptDraft,
        segments,
        keyframes,
        renderTaskId,
        currentStep,
      })
    ) {
      return
    }

    const timer = window.setTimeout(() => {
      const payload = buildProjectPayload({ state: stateForSave })

      const persist = async () => {
        try {
          if (selectedProjectId) {
            await scriptPipelineApi.updateProject(selectedProjectId, payload)
            return
          }

          if (creatingProjectRef.current) {
            return
          }

          creatingProjectRef.current = true
          const response = await scriptPipelineApi.createProject(payload)
          setCurrentProjectId(response.data.item.id)
        } catch {
          message.error('项目自动保存失败')
        } finally {
          creatingProjectRef.current = false
        }
      }

      void persist()
    }, 800)

    return () => window.clearTimeout(timer)
  }, [
    aspectRatio,
    cameraFixed,
    constraintCharacterIds,
    constraintSceneIds,
    currentStep,
    generatedScript,
    manualCharacterProfiles,
    savedTemporaryCharacterIds,
    generateAudio,
    keyframes,
    keyframeLoading,
    maxSegmentDuration,
    projectHydrating,
    projectTitle,
    provider,
    providerModel,
    referenceImages,
    renderTaskId,
    resolution,
    returnLastFrame,
    scriptDraft,
    scriptSummary,
    splitValidationReport,
    seedInput,
    segments,
    selectedCharacterIds,
    selectedSceneIds,
    serviceTier,
    stylePreference,
    targetTotalDuration,
    transitionDirection,
    userInput,
    watermark,
    workflowMode,
    renderStatus,
    selectedProjectId,
    setCurrentProjectId,
  ])

  const handleReferenceUpload: UploadProps['customRequest'] = async (options) => {
    const file = options.file as File
    try {
      const response = await scriptPipelineApi.uploadReferenceImage(file)
      const asset = response.data
      const uploadItem: UploadFile = {
        uid: asset.id,
        name: asset.original_filename || asset.filename,
        status: 'done',
        url: resolveAssetUrl(asset.url),
      }

      setReferenceImages((previous) => [...previous, asset])
      setUploadFileList((previous) => [...previous, uploadItem])
      message.success(`${file.name} 上传成功`)
      options.onSuccess?.(asset)
    } catch (uploadError) {
      const detail = extractApiErrorMessage(uploadError, '参考图上传失败')
      message.error(detail)
      options.onError?.(new Error(detail))
    }
  }

  const handleReferenceRemove: UploadProps['onRemove'] = (file) => {
    setUploadFileList((previous) => previous.filter((item) => item.uid !== file.uid))
    setReferenceImages((previous) => previous.filter((item) => item.id !== file.uid))
    return true
  }

  const runGenerateScript = async ({
    libraryCharacterIds,
    temporaryCharacters,
  }: {
    libraryCharacterIds: string[]
    temporaryCharacters: CharacterProfile[]
  }) => {
    if (!userInput.trim()) {
      return
    }

    let ensuredProjectId: string | null = null

    try {
      ensuredProjectId = await ensureProjectExists()

      setCurrentStep(1)
      setScriptLoading(true)
      setError(null)
      setGeneratedScript(null)
      setManualCharacterProfiles([])
      setSavedTemporaryCharacterIds([])
      setSegments([])
      setSplitValidationReport(null)
      setKeyframes([])
      setRenderTaskId(null)
      setRenderStatus(null)

      const response = await scriptPipelineApi.generateScript({
        project_id: ensuredProjectId,
        user_input: userInput.trim(),
        style: stylePreference.trim(),
        target_total_duration: targetTotalDuration || undefined,
        workflow_mode: workflowMode,
        selected_character_ids: libraryCharacterIds,
        selected_scene_ids: constraintSceneIds,
        character_profiles: temporaryCharacters,
        reference_images: referenceImages,
        generation_intent: characterPrepareResult?.generation_intent,
        character_resolution: characterPrepareResult?.character_resolution as Record<string, unknown> | undefined,
      })
    setGeneratedScript(response.data)
    setCharacterPrepareResult(null)
    setCharacterConfirmOpen(false)
    setSavedTemporaryCharacterIds([])
    setScriptDraft(response.data.script_text)
      setScriptSummary(buildSummary(response.data))
      setSelectedCharacterIds(response.data.selected_character_ids || [])
      setSelectedSceneIds(response.data.selected_scene_ids || [])
      setProjectTitle(response.data.summary.title || '未命名项目')
      setCurrentStep(1)
    } catch (requestError: unknown) {
      if (ensuredProjectId && isGatewayTimeoutError(requestError)) {
        try {
          const recovered = await recoverGeneratedScriptFromProject(ensuredProjectId, requestError)
          if (recovered) {
            return
          }
        } catch (recoveryError) {
          setError(extractApiErrorMessage(recoveryError, '完整剧本生成失败'))
          setCurrentStep(0)
          return
        }
      }
      setError(extractApiErrorMessage(requestError, '完整剧本生成失败'))
      setCurrentStep(0)
    } finally {
      setScriptLoading(false)
    }
  }

  const handleGenerateScript = async () => {
    if (!userInput.trim()) {
      return
    }

    setPreparingCharacters(true)
    setError(null)
    setCharacterPrepareResult(null)
    setCharacterConfirmOpen(false)
    setConfirmedLibraryCharacterIds([])
    setConfirmedTemporaryCharacterIds([])
    setCharacterConfirmMode('generate_script')

    try {
      const response = await scriptPipelineApi.prepareCharacters({
        user_input: userInput.trim(),
        style: stylePreference.trim(),
        target_total_duration: targetTotalDuration || undefined,
        selected_character_ids: constraintCharacterIds,
      })
      setCharacterPrepareResult(response.data)
      setConfirmedLibraryCharacterIds(response.data.selected_character_ids || [])
      setConfirmedTemporaryCharacterIds((response.data.temporary_character_profiles || []).map((item) => item.id))
      setCharacterConfirmOpen(true)
    } catch (requestError: unknown) {
      setCharacterPrepareResult(null)
      setCharacterConfirmOpen(false)
      setError(extractApiErrorMessage(requestError, '角色确认分析失败'))
    } finally {
      setPreparingCharacters(false)
    }
  }

  const buildConfirmedCharacterProfiles = (
    prepareResult: PrepareCharactersResponse | null,
    libraryCharacterIds: string[],
    temporaryCharacterIds: string[],
  ): CharacterProfile[] => {
    if (!prepareResult) {
      return []
    }

    const selectedLibraryProfiles = (prepareResult.library_character_profiles || []).filter((profile) =>
      libraryCharacterIds.includes(profile.id),
    )
    const selectedTemporaryProfiles = (prepareResult.temporary_character_profiles || []).filter((profile) =>
      temporaryCharacterIds.includes(profile.id),
    )

    return [...selectedLibraryProfiles, ...selectedTemporaryProfiles]
  }

  const runReviewSplitScript = async ({
    projectId,
    scriptText,
    segmentsToReview,
    maxDuration,
    targetDuration,
    silentOnError = false,
  }: {
    projectId?: string | null
    scriptText: string
    segmentsToReview: SegmentItem[]
    maxDuration: number
    targetDuration: number | null
    silentOnError?: boolean
  }) => {
    if (!scriptText.trim() || !segmentsToReview.length || splitReviewLoading) {
      return
    }

    setSplitReviewLoading(true)
    try {
      const response = await scriptPipelineApi.reviewSplitScript({
        project_id: projectId || undefined,
        script_text: scriptText.trim(),
        max_segment_duration: maxDuration,
        target_total_duration: targetDuration || undefined,
        workflow_mode: workflowMode,
        segments: segmentsToReview,
      })
      setSegments(normalizeSegmentItems(response.data.segments || segmentsToReview))
      setSplitValidationReport(response.data.validation_report || null)
    } catch (requestError: unknown) {
      setSplitValidationReport(null)
      if (!silentOnError) {
        message.error(extractApiErrorMessage(requestError, '片段审核失败'))
      }
    } finally {
      setSplitReviewLoading(false)
    }
  }

  const runSplitScript = async () => {
    if (!scriptDraft.trim() || splitRequestInFlightRef.current) {
      return
    }

    splitRequestInFlightRef.current = true
    const normalizedMaxSegmentDuration = normalizeMaxSegmentDuration(maxSegmentDuration)
    const normalizedScriptDraft = scriptDraft.trim()
    let ensuredProjectId: string | null = null

    setCurrentStep(2)
    setSplitLoading(true)
    setSplitReviewLoading(false)
    setError(null)
    setSegments([])
    setSplitValidationReport(null)
    setKeyframes([])
    setRenderTaskId(null)
    setRenderStatus(null)
    setMaxSegmentDuration(normalizedMaxSegmentDuration)

    try {
      ensuredProjectId = await ensureProjectExists()
      const response = await scriptPipelineApi.splitScript({
        project_id: ensuredProjectId,
        script_text: normalizedScriptDraft,
        max_segment_duration: normalizedMaxSegmentDuration,
        target_total_duration: targetTotalDuration || undefined,
        workflow_mode: workflowMode,
      })
      const normalizedSegments = normalizeSegmentItems(response.data.segments)
      setSegments(normalizedSegments)
      setSplitValidationReport(response.data.validation_report || null)
      setKeyframes([])
      setCurrentStep(2)
      void runReviewSplitScript({
        projectId: ensuredProjectId,
        scriptText: normalizedScriptDraft,
        segmentsToReview: normalizedSegments,
        maxDuration: normalizedMaxSegmentDuration,
        targetDuration: targetTotalDuration ?? null,
        silentOnError: true,
      })
    } catch (requestError: unknown) {
      if (ensuredProjectId && isGatewayTimeoutError(requestError)) {
        try {
          const recovered = await recoverSplitScriptFromProject(
            ensuredProjectId,
            {
              scriptText: normalizedScriptDraft,
              maxSegmentDuration: normalizedMaxSegmentDuration,
              targetTotalDuration: targetTotalDuration ?? null,
              workflowMode,
            },
            requestError,
          )
          if (recovered) {
            return
          }
        } catch (recoveryError) {
          setError(extractApiErrorMessage(recoveryError, '视频片段拆分失败'))
          setCurrentStep(1)
          return
        }
      }
      setError(extractApiErrorMessage(requestError, '视频片段拆分失败'))
      setCurrentStep(1)
    } finally {
      splitRequestInFlightRef.current = false
      setSplitLoading(false)
    }
  }

  const handleConfirmCharactersAndContinue = async () => {
    const temporaryCharacters = (characterPrepareResult?.temporary_character_profiles || []).filter((profile) =>
      confirmedTemporaryCharacterIds.includes(profile.id),
    )
    const confirmedProfiles = buildConfirmedCharacterProfiles(
      characterPrepareResult,
      confirmedLibraryCharacterIds,
      confirmedTemporaryCharacterIds,
    )

    setSelectedCharacterIds(confirmedLibraryCharacterIds)

    if (characterConfirmMode === 'split_script') {
      setManualCharacterProfiles(confirmedProfiles)
      setSavedTemporaryCharacterIds([])
      setCharacterConfirmOpen(false)
      await runSplitScript()
      return
    }

    await runGenerateScript({
      libraryCharacterIds: confirmedLibraryCharacterIds,
      temporaryCharacters,
    })
  }

  const handleSaveTemporaryCharacter = async (profile: CharacterProfile, firstFrameReference: KeyframeAsset | null) => {
    const profileId = profile.id
    if (!profileId || savingTemporaryCharacterIds.includes(profileId)) {
      return
    }
    if (!firstFrameReference?.asset_url) {
      message.warning('当前角色还没有可用的首帧参考图，暂时不能保存到角色档案库')
      return
    }

    setSavingTemporaryCharacterIds((previous) => [...previous, profileId])
    try {
      const response = await scriptPipelineApi.createCharacter({
        name: profile.name,
        category: profile.category,
        role: profile.role,
        archetype: profile.archetype,
        age_range: profile.age_range,
        gender_presentation: profile.gender_presentation,
        description: profile.description,
        appearance: profile.appearance,
        personality: profile.personality,
        core_appearance: profile.core_appearance,
        hair: profile.hair,
        face_features: profile.face_features,
        body_shape: profile.body_shape,
        outfit: profile.outfit,
        gear: profile.gear,
        color_palette: profile.color_palette,
        visual_do_not_change: profile.visual_do_not_change,
        speaking_style: profile.speaking_style,
        common_actions: profile.common_actions,
        emotion_baseline: profile.emotion_baseline,
        voice_description: profile.voice_description,
        forbidden_behaviors: profile.forbidden_behaviors,
        prompt_hint: profile.prompt_hint,
        llm_summary: profile.llm_summary,
        image_prompt_base: profile.image_prompt_base,
        video_prompt_base: profile.video_prompt_base,
        negative_prompt: profile.negative_prompt,
        tags: profile.tags,
        must_keep: profile.must_keep,
        forbidden_traits: profile.forbidden_traits,
        aliases: profile.aliases,
        profile_version: profile.profile_version,
        source: 'library',
        reference_image_url: firstFrameReference.asset_url,
        reference_image_original_name: firstFrameReference.asset_filename || `${profile.name}-first-frame.png`,
        auto_generate_identity_assets: false,
      })
      const createdProfile = response.data
      setCharacterProfiles((previous) => [createdProfile, ...previous.filter((item) => item.id !== createdProfile.id)])
      setSavedTemporaryCharacterIds((previous) => [...new Set([...previous, profileId])])
      message.success(`已将临时角色「${profile.name}」保存到角色档案库`)
    } catch (requestError: unknown) {
      message.error(extractApiErrorMessage(requestError, '保存临时角色失败'))
    } finally {
      setSavingTemporaryCharacterIds((previous) => previous.filter((item) => item !== profileId))
    }
  }

  const handleSplitScript = async () => {
    if (!scriptDraft.trim()) {
      return
    }

    setError(null)
    if (!generatedScript) {
      setPreparingCharacters(true)
      setCharacterPrepareResult(null)
      setCharacterConfirmOpen(false)
      setConfirmedLibraryCharacterIds([])
      setConfirmedTemporaryCharacterIds([])
      setCharacterConfirmMode('split_script')

      try {
        const response = await scriptPipelineApi.prepareCharacters({
          user_input: scriptDraft.trim(),
          style: stylePreference.trim(),
          target_total_duration: targetTotalDuration || undefined,
          selected_character_ids: constraintCharacterIds,
          character_profiles: manualCharacterProfiles,
        })
        setCharacterPrepareResult(response.data)
        setConfirmedLibraryCharacterIds(response.data.selected_character_ids || [])
        setConfirmedTemporaryCharacterIds((response.data.temporary_character_profiles || []).map((item) => item.id))
        setCharacterConfirmOpen(true)
      } catch (requestError: unknown) {
        setCharacterPrepareResult(null)
        setCharacterConfirmOpen(false)
        setError(extractApiErrorMessage(requestError, '角色确认分析失败'))
      } finally {
        setPreparingCharacters(false)
      }
      return
    }

    await runSplitScript()
  }

  const handleSegmentChange = (index: number, patch: Partial<SegmentItem>) => {
    setSplitValidationReport(null)
    setSegments((previous) =>
      previous.map((segment, segmentIndex) =>
        segmentIndex === index ? normalizeSegmentItem({ ...segment, ...patch }) : segment,
      ),
    )
  }

  const handleGenerateKeyframes = async (targetSegmentNumber?: number) => {
    if (!segments.length || keyframeRequestInFlightRef.current) {
      return
    }

    keyframeRequestInFlightRef.current = true
    const partialRegeneration = Number.isFinite(targetSegmentNumber)
    const normalizedSegments = normalizeSegmentItems(segments)
    const normalizedStyle = stylePreference.trim()
    const requestSelectedCharacterIds = [...selectedCharacterIds]
    const requestSelectedSceneIds = [...selectedSceneIds]
    let ensuredProjectId: string | null = null

    setCurrentStep(3)
    setKeyframeLoading(true)
    setKeyframeRegeneratingSegmentNumber(partialRegeneration ? Number(targetSegmentNumber) : null)
    setError(null)
    setRenderTaskId(null)
    setRenderStatus(null)
    setSegments(normalizedSegments)
    if (!partialRegeneration) {
      setKeyframes([])
    }

    try {
      ensuredProjectId = await ensureProjectExists()
      const response = await scriptPipelineApi.generateKeyframes({
        project_id: ensuredProjectId,
        project_title: projectTitle.trim() || '未命名项目',
        style: normalizedStyle,
        workflow_mode: workflowMode,
        selected_character_ids: requestSelectedCharacterIds,
        selected_scene_ids: requestSelectedSceneIds,
        character_profiles: effectiveCharacterProfiles,
        scene_profiles: generatedScript?.scene_profiles || [],
        reference_images: referenceImages,
        segments: normalizedSegments,
        existing_keyframes: partialRegeneration ? keyframes : [],
        target_segment_number: partialRegeneration ? Number(targetSegmentNumber) : undefined,
      })
      setKeyframes(response.data.keyframes)
      setCurrentStep(3)
      if (partialRegeneration) {
        message.success(response.data.message || `已重新生成片段 ${Number(targetSegmentNumber)} 首帧`)
      }
    } catch (requestError: unknown) {
      if (ensuredProjectId && isGatewayTimeoutError(requestError)) {
        try {
          const recovered = await recoverKeyframesFromProject(
            ensuredProjectId,
            {
              style: normalizedStyle,
              selectedCharacterIds: requestSelectedCharacterIds,
              selectedSceneIds: requestSelectedSceneIds,
              referenceImages,
              segments: normalizedSegments,
              workflowMode,
            },
            requestError,
          )
          if (recovered) {
            return
          }
        } catch (recoveryError) {
          setError(extractApiErrorMessage(recoveryError, '首尾帧生成失败'))
          if (!partialRegeneration) {
            setCurrentStep(2)
          }
          return
        }
      }
      setError(
        extractApiErrorMessage(
          requestError,
          partialRegeneration ? `片段 ${Number(targetSegmentNumber)} 首帧重新生成失败` : '首尾帧生成失败',
        ),
      )
      if (!partialRegeneration) {
        setCurrentStep(2)
      }
    } finally {
      keyframeRequestInFlightRef.current = false
      setKeyframeLoading(false)
      setKeyframeRegeneratingSegmentNumber(null)
    }
  }

  const handleStartRender = async (autoContinueSegments = false) => {
    const currentRenderStatus = renderStatus
    if (currentRenderStatus?.status === 'paused' && renderTaskId) {
      await handleResumeRender(autoContinueSegments)
      return
    }

    if (currentRenderStatus && ['queued', 'dispatching', 'processing'].includes(currentRenderStatus.status)) {
      setCurrentStep(4)
      message.info('当前已有渲染任务在执行，已切换到渲染进度页')
      return
    }

    if (!segments.length) {
      return
    }

    const normalizedSegments = normalizeSegmentItems(segments)

    setCurrentStep(4)
    setRenderStarting(true)
    setError(null)
    setRenderTaskId(null)
    setRenderStatus(null)
    setSegments(normalizedSegments)

    try {
      const response = await scriptPipelineApi.renderProject({
        project_id: selectedProjectId || undefined,
        project_title: projectTitle.trim() || '未命名项目',
        provider,
        resolution,
        aspect_ratio: aspectRatio,
        watermark,
        provider_model: providerModel,
        camera_fixed: cameraFixed,
        generate_audio: generateAudio,
        return_last_frame: isLongShotWorkflow ? returnLastFrame : false,
        auto_continue_segments: autoContinueSegments,
        service_tier: serviceTier,
        seed: seedInput === null ? undefined : seedInput,
        workflow_mode: workflowMode,
        selected_character_ids: selectedCharacterIds,
        selected_scene_ids: selectedSceneIds,
        character_profiles: effectiveCharacterProfiles,
        scene_profiles: generatedScript?.scene_profiles || [],
        segments: normalizedSegments,
        keyframes,
      })
      setRenderTaskId(response.data.task_id)
      setCurrentStep(4)
    } catch (requestError: unknown) {
      setError(extractApiErrorMessage(requestError, '渲染任务启动失败'))
      setCurrentStep(3)
    } finally {
      setRenderStarting(false)
    }
  }

  const confirmRestartRender = (autoContinueSegments: boolean) => {
    const actionLabel = autoContinueSegments ? '一键全部重新生成' : '重新从第一段开始生成'
    Modal.confirm({
      title: actionLabel,
      content: '这会重新创建一个新的整段渲染任务，已完成片段不会复用，可能继续消耗较多 token。确认继续吗？',
      okText: '确认重生成',
      cancelText: '取消',
      onOk: async () => {
        await handleStartRender(autoContinueSegments)
      },
    })
  }

  const handleCancelRender = async () => {
    if (!renderTaskId) {
      return
    }

    setRenderActionLoading(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.cancelRenderTask(renderTaskId)
      setRenderStatus(response.data)
      message.success('渲染任务已取消')
    } catch (requestError: unknown) {
      message.error(extractApiErrorMessage(requestError, '取消渲染任务失败'))
    } finally {
      setRenderActionLoading(false)
    }
  }

  const handlePauseRender = async () => {
    if (!renderTaskId) {
      return
    }

    setRenderActionLoading(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.pauseRenderTask(renderTaskId)
      setRenderStatus(response.data)
      message.success('暂停请求已提交，当前片段完成后会停止')
    } catch (requestError: unknown) {
      message.error(extractApiErrorMessage(requestError, '暂停渲染任务失败'))
    } finally {
      setRenderActionLoading(false)
    }
  }

  const handleResumeRender = async (autoContinueSegments?: boolean) => {
    if (!renderTaskId) {
      return
    }

    setRenderActionLoading(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.resumeRenderTask(renderTaskId, {
        auto_continue_segments: autoContinueSegments ?? null,
      })
      setRenderStatus(response.data)
      setCurrentStep(4)
      message.success('渲染任务已继续')
    } catch (requestError: unknown) {
      message.error(extractApiErrorMessage(requestError, '继续渲染任务失败'))
    } finally {
      setRenderActionLoading(false)
    }
  }

  const handleRetryRender = async () => {
    if (!renderTaskId) {
      return
    }

    setRenderActionLoading(true)
    setRenderStarting(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.retryRenderTask(renderTaskId)
      setRenderTaskId(response.data.task_id)
      setRenderStatus(null)
      setCurrentStep(4)
      message.success(response.data.message || '渲染任务已重新启动')
    } catch (requestError: unknown) {
      message.error(extractApiErrorMessage(requestError, '重试渲染任务失败'))
    } finally {
      setRenderActionLoading(false)
      setRenderStarting(false)
    }
  }

  const handleRetryRenderClip = async (clipNumber: number) => {
    if (!renderTaskId) {
      return
    }

    setRenderActionLoading(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.retryRenderClip(renderTaskId, clipNumber)
      setRenderStatus(response.data)
      setCurrentStep(4)
      message.success(`片段 ${clipNumber} 已重新提交生成`)
    } catch (requestError: unknown) {
      message.error(extractApiErrorMessage(requestError, `片段 ${clipNumber} 重生成失败`))
    } finally {
      setRenderActionLoading(false)
    }
  }

  const handleReset = async () => {
    suppressProjectSaveRef.current = true
    resetLocalState()
    clearCurrentProjectId()
    try {
      const response = await scriptPipelineApi.createProject({
        project_title: '未命名项目',
        current_step: 0,
        state: {},
        status: 'draft',
      })
      setCurrentProjectId(response.data.item.id)
      setProjectTitle(response.data.item.project_title || '未命名项目')
      message.success('已创建新项目')
    } catch {
      message.error('新项目创建失败')
    } finally {
      suppressProjectSaveRef.current = false
    }
  }

  const goToStep = (stepIndex: number) => {
    if (isStepAvailable(stepIndex)) {
      setTransitionDirection(stepIndex >= currentStep ? 'forward' : 'backward')
      setCurrentStep(stepIndex)
    }
  }

  const isStepAvailable = (stepIndex: number) => {
    const availability = [
      true,
      !!generatedScript || !!scriptDraft.trim() || scriptLoading,
      segments.length > 0 || splitLoading,
      keyframes.length > 0 || keyframeLoading,
      !!renderTaskId || renderStarting || !!renderStatus,
      !!renderStatus?.clips?.length || renderStatus?.status === 'completed',
    ]
    return availability[stepIndex]
  }

  useEffect(() => {
    if (provider === 'doubao' && !providerModel.startsWith('doubao-')) {
      setProviderModel(DEFAULT_DOUBAO_MODEL)
      return
    }
    if (provider !== 'doubao' && !providerModel.startsWith('kling-')) {
      setProviderModel(DEFAULT_KLING_MODEL)
    }
  }, [provider, providerModel])

  const stepItems = buildStepItems(workflowMode)
  const isLongShotWorkflow = workflowMode === WORKFLOW_MODE_LONG_SHOT
  const constrainedCharacters = characterProfiles.filter((profile) => constraintCharacterIds.includes(profile.id))
  const constrainedScenes = sceneProfiles.filter((profile) => constraintSceneIds.includes(profile.id))
  const effectiveCharacterProfiles = generatedScript?.character_profiles || manualCharacterProfiles
  const temporaryCharacters = effectiveCharacterProfiles.filter((profile) => profile.source === 'ai-generated-draft')
  const characterResolution = generatedScript?.character_resolution
  const finalPreviewUrl = renderStatus?.final_output?.asset_url
  const finalPreviewType = renderStatus?.final_output?.asset_type
  const previousStepIndex = Math.max(currentStep - 1, 0)
  const nextStepIndex = Math.min(currentStep + 1, stepItems.length - 1)
  const canPauseRender = renderStatus ? ['queued', 'dispatching', 'processing'].includes(renderStatus.status) : false
  const canCancelRender = canPauseRender
  const canResumeRender = renderStatus?.status === 'paused'
  const canRetryRender = renderStatus ? ['failed', 'cancelled'].includes(renderStatus.status) : false
  const canRetrySingleClip = renderStatus ? ['paused', 'failed', 'cancelled', 'completed'].includes(renderStatus.status) : false
  const awaitingClipConfirmation = Boolean(renderStatus?.awaiting_confirmation)
  const nextClipNumber = renderStatus?.next_clip_number || null
  const lastCompletedClipNumber = renderStatus?.last_completed_clip_number || null
  const hasExistingRenderTask = Boolean(renderTaskId && renderStatus)
  const hasCompletedRenderClips = Boolean(
    (renderStatus?.clips || []).some((clip) => clip.status === 'completed' && clip.asset_url),
  )
  const renderedTemporaryCharacters = temporaryCharacters.filter((profile) =>
    segments.some((segment) => (segment.character_profile_ids || []).includes(profile.id)),
  )
  const temporaryCharacterSaveEntries = renderedTemporaryCharacters
    .filter((profile) => !savedTemporaryCharacterIds.includes(profile.id))
    .map((profile) => ({
      profile,
      firstFrameReference: findCharacterFirstFrameReference(profile.id, segments, keyframes),
    }))
  const shouldPromptSaveTemporaryCharacters =
    renderStatus?.status === 'completed' && temporaryCharacterSaveEntries.length > 0

  const renderStepContent = () => {
    if (currentStep === 0) {
      return (
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Card
            title="创意输入"
            extra={
              <Button icon={<TeamOutlined />} onClick={() => navigate('/characters/library')}>
                管理角色档案
              </Button>
            }
          >
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Alert
                type="info"
                showIcon
                message="建议直接输入创意需求与约束"
                description="系统会先做角色确认，再生成完整剧本，随后进入剧本审核与后续拆分流程。"
              />
              <TextArea
                rows={7}
                value={userInput}
                onChange={(event) => setUserInput(event.target.value)}
                placeholder="输入一句话创意、场景描述，或直接粘贴完整剧本。"
              />
              <Row gutter={[16, 16]}>
                <Col xs={24} md={12}>
                  <Text>视觉风格</Text>
                  <Input
                    style={{ marginTop: 8 }}
                    value={stylePreference}
                    onChange={(event) => setStylePreference(event.target.value)}
                    placeholder="例如：写实战术电影感、低照度、胶片颗粒"
                  />
                </Col>
                <Col xs={24} md={12}>
                  <Text>项目名称</Text>
                  <Input
                    style={{ marginTop: 8 }}
                    value={projectTitle}
                    onChange={(event) => setProjectTitle(event.target.value)}
                    placeholder="用于最终成片命名"
                  />
                </Col>
                <Col xs={24} md={12}>
                  <Text>视频流程</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    value={workflowMode}
                    onChange={(value) => setWorkflowMode(value)}
                    options={[
                      { value: WORKFLOW_MODE_STANDARD, label: '标准视频' },
                      { value: WORKFLOW_MODE_LONG_SHOT, label: '长镜头视频' },
                    ]}
                  />
                </Col>
                <Col xs={24} md={12}>
                  <Text>单片段最大时长</Text>
                  <InputNumber
                    min={3}
                    max={MAX_SEGMENT_DURATION}
                    style={{ width: '100%', marginTop: 8 }}
                    value={maxSegmentDuration}
                    onChange={(value) =>
                      setMaxSegmentDuration(normalizeMaxSegmentDuration(Number(value) || MAX_SEGMENT_DURATION))
                    }
                  />
                </Col>
                <Col xs={24} md={12}>
                  <Text>目标总时长（可选）</Text>
                  <InputNumber
                    min={10}
                    max={300}
                    style={{ width: '100%', marginTop: 8 }}
                    value={targetTotalDuration}
                    onChange={(value) => setTargetTotalDuration(value === null ? null : Number(value))}
                  />
                </Col>
              </Row>
            </Space>
          </Card>

          <Card style={{ borderRadius: 20 }}>
            <Collapse
              ghost
              items={[
                {
                  key: 'advanced-constraints',
                  label: (
                    <Space direction="vertical" size={2}>
                      <Text strong>高级约束（可选）</Text>
                      <Text type="secondary">
                        默认不填也可以，系统会先分析你的输入；如果你想强制指定角色、场景或参考图，再展开这里。
                      </Text>
                    </Space>
                  ),
                  children: (
                    <Space direction="vertical" size={16} style={{ width: '100%' }}>
                      <Alert
                        type="info"
                        showIcon
                        message="这里是手动约束入口，不是必填项"
                        description="角色和场景都支持多选。你可以提前指定正式档案，让后续剧本、图片和视频生成更稳定。"
                      />

                      <div>
                        <Text>选择角色档案</Text>
                        <Select
                          mode="multiple"
                          allowClear
                          loading={charactersLoading}
                          style={{ width: '100%', marginTop: 8 }}
                          value={constraintCharacterIds}
                          onChange={setConstraintCharacterIds}
                          placeholder="可多选。留空则由系统先分析用户输入，再匹配角色。"
                          options={characterProfiles.map((profile) => ({
                            value: profile.id,
                            label: `${profile.name}${profile.role ? ` · ${profile.role}` : ''}`,
                          }))}
                        />
                      </div>

                      {constrainedCharacters.length ? (
                        <Card type="inner" size="small" title="已选角色">
                          <Space wrap>
                            {constrainedCharacters.map((profile) => (
                              <Tag key={profile.id} color="processing">
                                {profile.name}
                              </Tag>
                            ))}
                          </Space>
                        </Card>
                      ) : null}

                      <div>
                        <Text>选择场景档案</Text>
                        <Select
                          mode="multiple"
                          allowClear
                          loading={scenesLoading}
                          style={{ width: '100%', marginTop: 8 }}
                          value={constraintSceneIds}
                          onChange={setConstraintSceneIds}
                          placeholder="可多选。留空则由系统根据剧情自动分析和匹配场景。"
                          options={sceneProfiles.map((profile) => ({
                            value: profile.id,
                            label: `${profile.name}${profile.location ? ` · ${profile.location}` : ''}`,
                          }))}
                        />
                      </div>

                      {constrainedScenes.length ? (
                        <Card type="inner" size="small" title="已选场景">
                          <Space wrap>
                            {constrainedScenes.map((profile) => (
                              <Tag key={profile.id} color="green">
                                {profile.name}
                              </Tag>
                            ))}
                          </Space>
                        </Card>
                      ) : null}

                      <div>
                        <Text>参考图上传</Text>
                        <Upload
                          listType="picture-card"
                          multiple
                          customRequest={handleReferenceUpload}
                          onRemove={handleReferenceRemove}
                          fileList={uploadFileList}
                        >
                          {uploadFileList.length >= 6 ? null : (
                            <div>
                              <FileImageOutlined />
                              <div style={{ marginTop: 8 }}>上传参考图</div>
                            </div>
                          )}
                        </Upload>
                      </div>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
            <Button
              type="primary"
              size="large"
              icon={<PlayCircleOutlined />}
              loading={preparingCharacters || scriptLoading}
              disabled={!userInput.trim()}
              onClick={handleGenerateScript}
            >
              开始角色确认并生成剧本
            </Button>
          </div>
        </Space>
      )
    }

    if (currentStep === 1) {
      return (
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Card title="剧本确认">
            {scriptLoading ? (
              <div style={{ padding: '72px 0', textAlign: 'center' }}>
                <Spin size="large" />
                <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>正在生成完整剧本</Paragraph>
              </div>
            ) : (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {scriptSummary ? (
                  <Descriptions bordered size="small" column={{ xs: 1, lg: 2 }}>
                    <Descriptions.Item label="标题">{scriptSummary.title || '未命名剧本'}</Descriptions.Item>
                    <Descriptions.Item label="基调">{scriptSummary.tone || '未设置'}</Descriptions.Item>
                    <Descriptions.Item label="总时长">{scriptSummary.total_duration || 0} 秒</Descriptions.Item>
                    <Descriptions.Item label="角色数">{scriptSummary.character_count}</Descriptions.Item>
                    <Descriptions.Item label="场景数">{scriptSummary.scene_count}</Descriptions.Item>
                    <Descriptions.Item label="主题">
                      <Space wrap>
                        {(scriptSummary.themes || []).map((theme) => (
                          <Tag key={theme}>{theme}</Tag>
                        ))}
                      </Space>
                    </Descriptions.Item>
                    <Descriptions.Item label="简介" span={2}>
                      {scriptSummary.synopsis}
                    </Descriptions.Item>
                  </Descriptions>
                ) : null}

                {characterResolution?.message ? (
                  <Alert
                    type={characterResolution.needs_user_action ? 'warning' : temporaryCharacters.length ? 'info' : 'success'}
                    showIcon
                    message="角色来源分析"
                    description={
                      <Space direction="vertical" size={8} style={{ width: '100%' }}>
                        <Text>{characterResolution.message}</Text>
                        {characterResolution.needs_user_action ? (
                          <Space wrap>
                            <Button size="small" onClick={() => navigate('/characters/new')}>
                              去创建角色档案
                            </Button>
                            <Text type="secondary">如果继续生成，当前流程会缺少稳定角色模板，后续图像和视频一致性会更弱。</Text>
                          </Space>
                        ) : null}
                      </Space>
                    }
                  />
                ) : null}

                {temporaryCharacters.length ? (
                  <Card
                    size="small"
                    title="自动生成角色建议"
                    extra={
                      <Text type="secondary">
                        {isLongShotWorkflow
                          ? '可直接用于本次创作；生成视频后可按首帧造型保存到角色库'
                          : '可直接用于本次创作；标准流程默认不生成角色首帧锚点'}
                      </Text>
                    }
                  >
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      {temporaryCharacters.map((profile) => (
                        <Card
                          key={profile.id}
                          type="inner"
                          size="small"
                          title={
                            <Space wrap>
                              <Tag color="gold">{profile.name}</Tag>
                              <Tag>临时角色</Tag>
                              {profile.role ? <Tag color="processing">{profile.role}</Tag> : null}
                            </Space>
                          }
                        >
                          <Space direction="vertical" size={6} style={{ width: '100%' }}>
                            {profile.llm_summary ? <Text>{profile.llm_summary}</Text> : null}
                            {profile.must_keep.length ? (
                              <Text type="secondary">必须保持：{profile.must_keep.join('、')}</Text>
                            ) : null}
                            {profile.image_prompt_base ? (
                              <Text type="secondary">图像基底：{profile.image_prompt_base}</Text>
                            ) : null}
                            {profile.video_prompt_base ? (
                              <Text type="secondary">视频基底：{profile.video_prompt_base}</Text>
                            ) : null}
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </Card>
                ) : null}

                <Alert
                  type="success"
                  showIcon
                  message="剧本内容已准备完成"
                  description="下面展示的是当前将用于分段的完整剧本。你可以直接修改文本；下一步会按时长与约束把它切成片段。"
                />

                <Card
                  size="small"
                  title="完整剧本"
                  extra={<Text type="secondary">可直接编辑，下一步会按约束切分剧本并生成分段结果</Text>}
                >
                  <TextArea
                    value={scriptDraft}
                    onChange={(event) => setScriptDraft(event.target.value)}
                    rows={20}
                    placeholder="这里会显示完整剧本内容，你可以继续修改。"
                  />
                </Card>
              </Space>
            )}
          </Card>

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Button onClick={() => setCurrentStep(0)}>返回输入</Button>
            <Space wrap>
              <Button loading={scriptLoading} disabled={!userInput.trim()} onClick={handleGenerateScript}>
                重新生成剧本
              </Button>
              <Button
                type="primary"
                loading={splitLoading || preparingCharacters}
                disabled={!scriptDraft.trim()}
                onClick={handleSplitScript}
              >
                按约束切分剧本
              </Button>
            </Space>
          </div>
        </Space>
      )
    }

    if (currentStep === 2) {
      return (
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Alert
            type={splitReviewLoading ? 'warning' : 'info'}
            showIcon
            message={
              splitReviewLoading
                ? `当前已拆分为 ${segments.length} 个片段，正在后台审核片段质量。`
                : `当前已拆分为 ${segments.length} 个片段。片段不做时间重叠，只保留画面连续性。`
            }
            description={splitReviewLoading ? '你可以先开始检查和编辑片段，审核报告会在完成后自动刷新。' : undefined}
          />
          {splitReviewLoading ? (
            <Card size="small" title="片段审核中">
              <Space align="center" size={12}>
                <Spin />
                <Text type="secondary">正在补充片段审核报告，这一步已从“拆分接口”中拆出，不会阻塞片段显示。</Text>
              </Space>
            </Card>
          ) : null}
          {splitValidationReport ? (
            <Card title="片段二次校验">
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Alert
                  showIcon
                  type={validationStatusToAlertType(splitValidationReport.status)}
                  message={splitValidationReport.summary || '拆分结果已完成二次校验'}
                  description={
                    <Space wrap>
                      <Tag color={validationStatusToTagColor(splitValidationReport.status)}>
                        {splitValidationReport.status === 'fail'
                          ? '未通过'
                          : splitValidationReport.status === 'warning'
                            ? '需关注'
                            : '通过'}
                      </Tag>
                      <Text>实际总时长：{splitValidationReport.actual_total_duration || 0} 秒</Text>
                      {splitValidationReport.target_total_duration ? (
                        <Text>目标总时长：{splitValidationReport.target_total_duration} 秒</Text>
                      ) : null}
                      {splitValidationReport.source ? <Text>校验来源：{splitValidationReport.source}</Text> : null}
                    </Space>
                  }
                />
                {splitValidationReport.checks?.length ? (
                  <Descriptions bordered size="small" column={1} title="校验项">
                    {splitValidationReport.checks.map((item) => (
                      <Descriptions.Item
                        key={item.code}
                        label={
                          <Space size={8}>
                            <span>{item.label}</span>
                            <Tag color={validationStatusToTagColor(item.status)}>
                              {item.status === 'fail' ? '未通过' : item.status === 'warning' ? '需关注' : '通过'}
                            </Tag>
                          </Space>
                        }
                      >
                        {item.detail}
                      </Descriptions.Item>
                    ))}
                  </Descriptions>
                ) : null}
                {splitValidationReport.issues?.length ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="全局问题"
                    description={
                      <Space direction="vertical" size={4}>
                        {splitValidationReport.issues.map((item, index) => (
                          <Text key={`${item}-${index}`}>{index + 1}. {item}</Text>
                        ))}
                      </Space>
                    }
                  />
                ) : null}
                {splitValidationReport.suggestions?.length ? (
                  <Alert
                    type="info"
                    showIcon
                    message="调整建议"
                    description={
                      <Space direction="vertical" size={4}>
                        {splitValidationReport.suggestions.map((item, index) => (
                          <Text key={`${item}-${index}`}>{index + 1}. {item}</Text>
                        ))}
                      </Space>
                    }
                  />
                ) : null}
              </Space>
            </Card>
          ) : null}
          <Card title="视频片段审核">
            {splitLoading ? (
              <div style={{ padding: '72px 0', textAlign: 'center' }}>
                <Spin size="large" />
                <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>正在拆分视频片段</Paragraph>
              </div>
            ) : segments.length ? (
              <Collapse
                accordion
                items={segments.map((segment, index) => ({
                  key: String(segment.segment_number),
                  label: (
                    <Space wrap>
                      <Tag color="processing">片段 {segment.segment_number}</Tag>
                      <Text>{segment.title}</Text>
                      <Tag>{segment.duration} 秒</Tag>
                    </Space>
                  ),
                  children: (
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      <Input
                        value={segment.title}
                        onChange={(event) => handleSegmentChange(index, { title: event.target.value })}
                        placeholder="片段标题"
                      />
                      <Row gutter={[12, 12]}>
                        <Col xs={24} md={8}>
                          <Text>片段时长</Text>
                          <InputNumber
                            min={1}
                            max={MAX_SEGMENT_DURATION}
                            style={{ width: '100%', marginTop: 8 }}
                            value={segment.duration}
                            onChange={(value) => handleSegmentChange(index, { duration: Number(value) || segment.duration })}
                          />
                        </Col>
                        <Col xs={24} md={8}>
                          <Text>开始时间</Text>
                          <InputNumber
                            min={0}
                            style={{ width: '100%', marginTop: 8 }}
                            value={segment.start_time}
                            onChange={(value) => handleSegmentChange(index, { start_time: Number(value) || 0 })}
                          />
                        </Col>
                        <Col xs={24} md={8}>
                          <Text>结束时间</Text>
                          <InputNumber
                            min={0}
                            style={{ width: '100%', marginTop: 8 }}
                            value={segment.end_time}
                            onChange={(value) => handleSegmentChange(index, { end_time: Number(value) || 0 })}
                          />
                        </Col>
                      </Row>
                      <TextArea
                        rows={5}
                        value={segment.description}
                        onChange={(event) => handleSegmentChange(index, { description: event.target.value })}
                        placeholder="片段描述"
                      />
                      <TextArea
                        rows={5}
                        value={formatSegmentDialoguesText(segment.key_dialogues)}
                        onChange={(event) =>
                          handleSegmentChange(index, {
                            key_dialogues: normalizeSegmentDialogues(
                              event.target.value
                                .split('\n')
                                .map((line) => line.trim())
                                .filter(Boolean),
                            ),
                          })
                        }
                        placeholder={'对白（每行一条）\n角色名 [角色ID]: 台词\n角色名 [情绪 / 语气]: 台词\n角色名 [角色ID] [情绪 / 语气]: 台词'}
                      />
                      {(() => {
                        const generationConfig = getSegmentGenerationConfig(segment)
                        const isMultiShot = isSegmentMultiShotEnabled(segment)
                        const multiShotPrompts = getSegmentMultiShotPrompts(segment)
                        const multiShotReason = String(generationConfig.kling_multi_shot_reason || '').trim()
                        const multiShotSource = String(generationConfig.kling_multi_shot_source || '').trim()

                        return (
                          <Card
                            size="small"
                            title="视频生成模式"
                            extra={
                              <Space size={8}>
                                <Text type="secondary">多镜头模式</Text>
                                <Switch
                                  checked={isMultiShot}
                                  onChange={(checked) =>
                                    handleSegmentChange(index, buildMultiShotPatch(segment, checked, multiShotPrompts))
                                  }
                                />
                              </Space>
                            }
                          >
                            <Space direction="vertical" size={10} style={{ width: '100%' }}>
                              <Space wrap>
                                <Tag color={isMultiShot ? 'processing' : 'default'}>
                                  {isMultiShot ? '多镜头 multi_prompt' : '单镜头 prompt'}
                                </Tag>
                                {multiShotSource ? <Tag>{multiShotSource}</Tag> : null}
                              </Space>
                              {multiShotReason ? (
                                <Alert
                                  type={isMultiShot ? 'info' : 'success'}
                                  showIcon
                                  message={isMultiShot ? '当前片段将按多镜头模式生成' : '当前片段将按单镜头模式生成'}
                                  description={multiShotReason}
                                />
                              ) : null}
                              {isMultiShot ? (
                                <TextArea
                                  rows={6}
                                  value={formatMultiShotPromptsText(multiShotPrompts)}
                                  onChange={(event) => {
                                    const nextPrompts = parseMultiShotPromptsText(event.target.value)
                                    handleSegmentChange(index, buildMultiShotPatch(segment, true, nextPrompts))
                                  }}
                                  placeholder={'多镜头分镜提示词（每行一个）\n分镜 1 prompt\n分镜 2 prompt\n分镜 3 prompt'}
                                />
                              ) : (
                                <TextArea
                                  rows={6}
                                  value={segment.video_prompt}
                                  onChange={(event) => handleSegmentChange(index, { video_prompt: event.target.value })}
                                  placeholder="视频画面描述"
                                />
                              )}
                            </Space>
                          </Card>
                        )
                      })()}
                      <Row gutter={[12, 12]}>
                        <Col xs={24} md={12}>
                          <TextArea
                            rows={3}
                            value={segment.continuity_from_prev}
                            onChange={(event) => handleSegmentChange(index, { continuity_from_prev: event.target.value })}
                            placeholder="承接上一片段"
                          />
                        </Col>
                        <Col xs={24} md={12}>
                          <TextArea
                            rows={3}
                            value={segment.continuity_to_next}
                            onChange={(event) => handleSegmentChange(index, { continuity_to_next: event.target.value })}
                            placeholder="过渡到下一片段"
                          />
                        </Col>
                      </Row>
                      {splitValidationReport?.segment_reviews?.find((item) => item.segment_number === segment.segment_number) ? (
                        (() => {
                          const review = splitValidationReport.segment_reviews.find(
                            (item) => item.segment_number === segment.segment_number,
                          )
                          if (!review) {
                            return null
                          }
                          return (
                            <Card
                              size="small"
                              title={
                                <Space size={8}>
                                  <span>片段审核结论</span>
                                  <Tag color={validationStatusToTagColor(review.status)}>
                                    {review.status === 'fail' ? '未通过' : review.status === 'warning' ? '需关注' : '通过'}
                                  </Tag>
                                </Space>
                              }
                            >
                              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                                <Text>{review.summary}</Text>
                                {review.issues?.length ? (
                                  <Alert
                                    type="warning"
                                    showIcon
                                    message="本段问题"
                                    description={
                                      <Space direction="vertical" size={4}>
                                        {review.issues.map((item, reviewIndex) => (
                                          <Text key={`${item}-${reviewIndex}`}>{reviewIndex + 1}. {item}</Text>
                                        ))}
                                      </Space>
                                    }
                                  />
                                ) : null}
                                {review.suggestions?.length ? (
                                  <Alert
                                    type="info"
                                    showIcon
                                    message="本段建议"
                                    description={
                                      <Space direction="vertical" size={4}>
                                        {review.suggestions.map((item, reviewIndex) => (
                                          <Text key={`${item}-${reviewIndex}`}>{reviewIndex + 1}. {item}</Text>
                                        ))}
                                      </Space>
                                    }
                                  />
                                ) : null}
                              </Space>
                            </Card>
                          )
                        })()
                      ) : null}
                    </Space>
                  ),
                }))}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先生成片段" />
            )}
          </Card>

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Button onClick={() => setCurrentStep(1)}>返回剧本</Button>
            <Space wrap>
              <Button loading={splitLoading} disabled={!scriptDraft.trim()} onClick={handleSplitScript}>
                重新生成片段
              </Button>
              <Button
                loading={splitReviewLoading}
                disabled={!scriptDraft.trim() || !segments.length}
                onClick={() =>
                  void runReviewSplitScript({
                    projectId: selectedProjectId || null,
                    scriptText: scriptDraft,
                    segmentsToReview: normalizeSegmentItems(segments),
                    maxDuration: normalizeMaxSegmentDuration(maxSegmentDuration),
                    targetDuration: targetTotalDuration ?? null,
                  })
                }
              >
                审核当前片段
              </Button>
              <Button
                type="primary"
                icon={<FileImageOutlined />}
                loading={keyframeLoading}
                onClick={() => void handleGenerateKeyframes()}
              >
                {isLongShotWorkflow ? '通过片段并生成首尾帧' : '通过片段并生成首帧预览'}
              </Button>
            </Space>
          </div>
        </Space>
      )
    }

    if (currentStep === 3) {
      if (!isLongShotWorkflow) {
        const previewKeyframes = keyframes.filter((bundle) => Boolean(bundle.start_frame.asset_url))
        const isFullKeyframeGenerationLoading = keyframeLoading && keyframeRegeneratingSegmentNumber === null
        return (
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message="标准视频流程会为每个片段生成首帧预览"
              description="这些图片用于帮助你快速理解每段视频的开场画面和内容重点，不参与跨段串联，也不会要求生成尾帧。"
            />

            <Card title="片段首帧预览">
              {isFullKeyframeGenerationLoading ? (
                <div style={{ padding: '72px 0', textAlign: 'center' }}>
                  <Spin size="large" />
                  <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>正在生成每个片段的首帧预览</Paragraph>
                </div>
              ) : previewKeyframes.length ? (
                <Space direction="vertical" size={20} style={{ width: '100%' }}>
                  {previewKeyframes.map((bundle) => (
                    <Card
                      key={`preview-${bundle.segment_number}`}
                      type="inner"
                      title={
                        <Space wrap>
                          <Tag color="processing">片段 {bundle.segment_number}</Tag>
                          <Text>{bundle.title}</Text>
                          <Tag color="success">首帧预览</Tag>
                        </Space>
                      }
                      extra={
                        <Button
                          size="small"
                          loading={keyframeRegeneratingSegmentNumber === bundle.segment_number}
                          disabled={keyframeLoading && keyframeRegeneratingSegmentNumber !== bundle.segment_number}
                          onClick={() => void handleGenerateKeyframes(bundle.segment_number)}
                        >
                          重新生成这一段
                        </Button>
                      }
                    >
                      <Row gutter={[20, 20]}>
                        <Col xs={24} lg={13}>
                          <Text strong>片段开场预览</Text>
                          <div style={{ marginTop: 12 }}>
                            <PreviewAsset
                              assetUrl={bundle.start_frame.asset_url}
                              thumbnailUrl={bundle.start_frame.thumbnail_url}
                              assetType={bundle.start_frame.asset_type}
                              title={`${bundle.title} 首帧预览`}
                            />
                          </div>
                        </Col>
                        <Col xs={24} lg={11}>
                          <Space direction="vertical" size={12} style={{ width: '100%' }}>
                            <Alert
                              type="success"
                              showIcon
                              message="这张图用于帮助你确认该片段的视觉重点"
                              description={bundle.continuity_notes}
                            />
                            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                              {bundle.start_frame.prompt || '未提供提示词'}
                            </Paragraph>
                            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                              来源: {bundle.start_frame.source || 'unknown'}
                              {bundle.start_frame.notes ? ` | ${bundle.start_frame.notes}` : ''}
                            </Paragraph>
                          </Space>
                        </Col>
                      </Row>
                    </Card>
                  ))}
                </Space>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先生成首帧预览" />
              )}
            </Card>

            <Card title="渲染参数">
              <Row gutter={[16, 16]}>
                <Col xs={24} md={8}>
                  <Text>视频引擎</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    value={provider}
                    onChange={setProvider}
                    options={[
                      { value: 'auto', label: '自动选择（可灵优先）' },
                      { value: 'kling', label: '可灵 Kling' },
                      { value: 'doubao', label: '豆包 Seedance' },
                      { value: 'local', label: '本地快速预览' },
                    ]}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Text>输出分辨率</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    value={resolution}
                    onChange={setResolution}
                    options={[
                      { value: '480p', label: '480p' },
                      { value: '720p', label: '720p' },
                      { value: '1080p', label: '1080p' },
                    ]}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Text>画幅比例</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    value={aspectRatio}
                    onChange={setAspectRatio}
                    options={[
                      { value: '16:9', label: '16:9' },
                      { value: '9:16', label: '9:16' },
                      { value: '1:1', label: '1:1' },
                      { value: '4:3', label: '4:3' },
                    ]}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Text>模型 ID</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    value={providerModel}
                    onChange={setProviderModel}
                    options={[
                      { value: 'kling-video-o1', label: 'Kling Video O1' },
                      { value: 'kling-v3-omni', label: 'Kling 3 Omni' },
                      { value: 'doubao-seedance-1-5-pro-251215', label: 'Seedance 1.5 Pro' },
                      { value: 'doubao-seedance-1-5-lite-241115', label: 'Seedance 1.5 Lite' },
                      { value: 'doubao-seedance-1-0-lite-i2v-250428', label: 'Seedance 1.0 Lite I2V' },
                    ]}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Text>服务等级</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    value={serviceTier}
                    onChange={setServiceTier}
                    options={[
                      { value: 'default', label: 'default' },
                      { value: 'flex', label: 'flex' },
                    ]}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Text>随机种子</Text>
                  <InputNumber
                    style={{ width: '100%', marginTop: 8 }}
                    value={seedInput}
                    onChange={(value) => setSeedInput(value === null ? null : Number(value))}
                    placeholder="留空则随机"
                  />
                </Col>
                <Col xs={24}>
                  <Space wrap size="large">
                    <Space>
                      <Switch checked={watermark} onChange={setWatermark} />
                      <Text>水印</Text>
                    </Space>
                    <Space>
                      <Switch checked={cameraFixed} onChange={setCameraFixed} />
                      <Text>固定镜头</Text>
                    </Space>
                    <Space>
                      <Switch checked={generateAudio} onChange={setGenerateAudio} />
                      <Text>视频模型音频</Text>
                    </Space>
                  </Space>
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                    开启后优先使用视频模型自带的音频能力；关闭后仅生成纯视频画面。
                  </Paragraph>
                </Col>
              </Row>
            </Card>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <Button onClick={() => setCurrentStep(2)}>返回片段</Button>
              <Space wrap>
                <Button loading={keyframeLoading} disabled={!segments.length} onClick={() => void handleGenerateKeyframes()}>
                  重新生成首帧预览
                </Button>
                <Button
                  type="primary"
                  icon={<VideoCameraOutlined />}
                  loading={renderStarting || renderActionLoading}
                  disabled={Boolean(renderStatus && ['queued', 'dispatching', 'processing'].includes(renderStatus.status))}
                  onClick={() => void handleStartRender(false)}
                >
                  {canResumeRender && awaitingClipConfirmation
                    ? '继续生成下一段'
                    : hasExistingRenderTask && hasCompletedRenderClips
                      ? '继续当前生成任务'
                      : '生成第一段视频'}
                </Button>
                <Button
                  loading={renderStarting || renderActionLoading}
                  disabled={
                    !segments.length || Boolean(renderStatus && ['queued', 'dispatching', 'processing'].includes(renderStatus.status))
                  }
                  onClick={() => void handleStartRender(true)}
                >
                  {canResumeRender && awaitingClipConfirmation
                    ? '一键全部生成剩余片段'
                    : hasExistingRenderTask && hasCompletedRenderClips
                      ? '继续生成剩余片段'
                      : '一键全部生成'}
                </Button>
              </Space>
            </div>
          </Space>
        )
      }

      const generatedKeyframes = keyframes.filter((bundle) => Boolean(bundle.start_frame.asset_url))
      const chainedKeyframes = keyframes.filter((bundle) => !bundle.start_frame.asset_url)
      const isFullKeyframeGenerationLoading = keyframeLoading && keyframeRegeneratingSegmentNumber === null

      return (
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="系统会按分段规则预生成必要的首帧；其余片段首帧会在渲染时自动复用上一段返回的尾帧。"
          />
          <Card title="首帧与串联方式确认">
            {isFullKeyframeGenerationLoading ? (
              <div style={{ padding: '72px 0', textAlign: 'center' }}>
                <Spin size="large" />
                <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>正在生成预设首帧</Paragraph>
              </div>
            ) : keyframes.length ? (
              <Space direction="vertical" size={20} style={{ width: '100%' }}>
                {generatedKeyframes.map((bundle, index) => (
                  <Card
                    key={`generated-${bundle.segment_number}`}
                    type="inner"
                    title={
                      <Space wrap>
                        <Tag color="processing">片段 {bundle.segment_number}</Tag>
                        <Text>{bundle.title}</Text>
                        <Tag color="success">{index === 0 ? '预生成首帧' : '额外首帧锚点'}</Tag>
                      </Space>
                    }
                    extra={
                      <Button
                        size="small"
                        loading={keyframeRegeneratingSegmentNumber === bundle.segment_number}
                        disabled={keyframeLoading && keyframeRegeneratingSegmentNumber !== bundle.segment_number}
                        onClick={() => void handleGenerateKeyframes(bundle.segment_number)}
                      >
                        重新生成这一段
                      </Button>
                    }
                  >
                    <Row gutter={[20, 20]}>
                      <Col xs={24} lg={13}>
                        <Text strong>{bundle.segment_number === 1 ? '起始首帧' : '额外角色锚定首帧'}</Text>
                        <div style={{ marginTop: 12 }}>
                          <PreviewAsset
                            assetUrl={bundle.start_frame.asset_url}
                            thumbnailUrl={bundle.start_frame.thumbnail_url}
                            assetType={bundle.start_frame.asset_type}
                            title={`${bundle.title} 首帧`}
                          />
                        </div>
                      </Col>
                      <Col xs={24} lg={11}>
                        <Space direction="vertical" size={12} style={{ width: '100%' }}>
                          <Alert
                            type="success"
                            showIcon
                            message={bundle.segment_number === 1 ? '这张图将作为整条长视频的起始画面' : '这张图会作为该段单独的起始锚点'}
                            description={bundle.continuity_notes}
                          />
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            {bundle.start_frame.prompt || '未提供提示词'}
                          </Paragraph>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            来源: {bundle.start_frame.source || 'unknown'}
                            {bundle.start_frame.notes ? ` | ${bundle.start_frame.notes}` : ''}
                          </Paragraph>
                        </Space>
                      </Col>
                    </Row>
                  </Card>
                ))}

                {chainedKeyframes.length ? (
                  <Card type="inner" title="后续片段串联方式">
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      {chainedKeyframes.map((bundle) => (
                        <Card
                          key={`chain-${bundle.segment_number}`}
                          size="small"
                          className="pipeline-chain-card"
                          extra={
                            <Button
                              size="small"
                              loading={keyframeRegeneratingSegmentNumber === bundle.segment_number}
                              disabled={keyframeLoading && keyframeRegeneratingSegmentNumber !== bundle.segment_number}
                              onClick={() => void handleGenerateKeyframes(bundle.segment_number)}
                            >
                              为这一段生成首帧
                            </Button>
                          }
                        >
                          <Space direction="vertical" size={6} style={{ width: '100%' }}>
                            <Space wrap>
                              <Tag color="processing">片段 {bundle.segment_number}</Tag>
                              <Text strong>{bundle.title}</Text>
                            </Space>
                            <Paragraph style={{ marginBottom: 0 }}>
                              该片段首帧不单独生成，将直接复用上一片段返回的尾帧。
                            </Paragraph>
                            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                              {bundle.start_frame.notes || bundle.continuity_notes}
                            </Paragraph>
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </Card>
                ) : null}
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先生成预设首帧" />
            )}
          </Card>

          <Card title="渲染参数">
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Text>视频引擎</Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  value={provider}
                  onChange={setProvider}
                  options={[
                    { value: 'auto', label: '自动选择（可灵优先）' },
                    { value: 'kling', label: '可灵 Kling' },
                    { value: 'doubao', label: '豆包 Seedance' },
                    { value: 'local', label: '本地快速预览' },
                  ]}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text>输出分辨率</Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  value={resolution}
                  onChange={setResolution}
                  options={[
                    { value: '480p', label: '480p' },
                    { value: '720p', label: '720p' },
                    { value: '1080p', label: '1080p' },
                  ]}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text>画幅比例</Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  value={aspectRatio}
                  onChange={setAspectRatio}
                  options={[
                    { value: '16:9', label: '16:9' },
                    { value: '9:16', label: '9:16' },
                    { value: '1:1', label: '1:1' },
                    { value: '4:3', label: '4:3' },
                  ]}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text>模型 ID</Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  value={providerModel}
                  onChange={setProviderModel}
                  options={[
                    { value: 'kling-video-o1', label: 'Kling Video O1' },
                    { value: 'kling-v3-omni', label: 'Kling 3 Omni' },
                    { value: 'doubao-seedance-1-5-pro-251215', label: 'Seedance 1.5 Pro' },
                    { value: 'doubao-seedance-1-5-lite-241115', label: 'Seedance 1.5 Lite' },
                    { value: 'doubao-seedance-1-0-lite-i2v-250428', label: 'Seedance 1.0 Lite I2V' },
                  ]}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text>服务等级</Text>
                <Select
                  style={{ width: '100%', marginTop: 8 }}
                  value={serviceTier}
                  onChange={setServiceTier}
                  options={[
                    { value: 'default', label: 'default' },
                    { value: 'flex', label: 'flex' },
                  ]}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text>随机种子</Text>
                <InputNumber
                  style={{ width: '100%', marginTop: 8 }}
                  value={seedInput}
                  onChange={(value) => setSeedInput(value === null ? null : Number(value))}
                  placeholder="留空则随机"
                />
              </Col>
              <Col xs={24}>
                <Space wrap size="large">
                  <Space>
                    <Switch checked={watermark} onChange={setWatermark} />
                    <Text>水印</Text>
                  </Space>
                  <Space>
                    <Switch checked={cameraFixed} onChange={setCameraFixed} />
                    <Text>固定镜头</Text>
                  </Space>
                  <Space>
                    <Switch checked={generateAudio} onChange={setGenerateAudio} />
                    <Text>视频模型音频</Text>
                  </Space>
                  <Space>
                    <Switch checked value disabled />
                    <Text>返回尾帧（串联模式固定开启）</Text>
                  </Space>
                </Space>
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  开启后优先使用视频模型自带的音频能力；关闭后仅生成纯视频画面。
                </Paragraph>
              </Col>
            </Row>
          </Card>

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Button onClick={() => setCurrentStep(2)}>返回片段</Button>
            <Space wrap>
              <Button loading={keyframeLoading} disabled={!segments.length} onClick={() => void handleGenerateKeyframes()}>
                重新生成首帧
              </Button>
              <Button
                type="primary"
                icon={<VideoCameraOutlined />}
                loading={renderStarting || renderActionLoading}
                disabled={Boolean(renderStatus && ['queued', 'dispatching', 'processing'].includes(renderStatus.status))}
                onClick={() => void handleStartRender(false)}
              >
                {canResumeRender && awaitingClipConfirmation
                  ? '继续生成下一段'
                  : hasExistingRenderTask && hasCompletedRenderClips
                    ? '继续当前生成任务'
                    : '生成第一段视频'}
              </Button>
              <Button
                loading={renderStarting || renderActionLoading}
                disabled={
                  !segments.length || Boolean(renderStatus && ['queued', 'dispatching', 'processing'].includes(renderStatus.status))
                }
                onClick={() => void handleStartRender(true)}
              >
                {canResumeRender && awaitingClipConfirmation
                  ? '一键全部生成剩余片段'
                  : hasExistingRenderTask && hasCompletedRenderClips
                    ? '继续生成剩余片段'
                    : '一键全部生成'}
              </Button>
            </Space>
          </div>
        </Space>
      )
    }

    if (currentStep === 4) {
      return (
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Card title="渲染进度">
            {renderStatus ? (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color={statusColorMap[renderStatus.status] || 'default'}>{renderStatus.status}</Tag>
                  <Tag>{renderStatus.current_step}</Tag>
                  <Tag>任务编号: {renderStatus.task_id}</Tag>
                </Space>
                <Progress percent={renderStatus.progress} status={renderStatus.status === 'failed' ? 'exception' : undefined} />
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  当前会优先输出正式视频结果；只有选择“本地快速预览”时，才会生成预览版画面。
                </Paragraph>
                <Alert
                  type="info"
                  showIcon
                  message="音频策略"
                  description={
                    renderStatus?.render_config?.generate_audio
                      ? '当前使用视频模型自带的音频能力，不再额外执行项目级音频后处理。'
                      : '当前已关闭音频生成，本次仅输出视频画面。'
                  }
                />
                {renderStatus.fallback_used ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="本次任务已自动调整生成方式。"
                    description={(renderStatus.warnings || []).join('；') || '请检查渲染设置、账号权限和片段输入。'}
                  />
                ) : null}
                {renderStatus.status === 'failed' && renderStatus.error ? (
                  <Alert type="error" showIcon message="渲染失败" description={renderStatus.error} />
                ) : null}
                {renderStatus.status === 'cancelled' ? (
                  <Alert type="info" showIcon message="渲染任务已取消" description="可以直接重试，系统会创建新的任务继续渲染。" />
                ) : null}
                {renderStatus.status === 'paused' ? (
                  <Alert
                    type={awaitingClipConfirmation ? 'info' : 'warning'}
                    showIcon
                    message={awaitingClipConfirmation ? '当前片段已生成完成，等待你确认后继续' : '渲染任务已暂停'}
                    description={
                      awaitingClipConfirmation
                        ? `片段 ${lastCompletedClipNumber || '-'} 已完成。确认无误后，再继续生成${nextClipNumber ? `片段 ${nextClipNumber}` : '下一段'}；如果确认整体没问题，也可以直接一键生成剩余全部片段。`
                        : '已完成片段会保留。继续任务后，会从未完成片段或待重生成片段继续执行。'
                    }
                  />
                ) : null}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
                  {canPauseRender ? (
                    <Button loading={renderActionLoading} onClick={handlePauseRender}>
                      暂停任务
                    </Button>
                  ) : null}
                  {canResumeRender && awaitingClipConfirmation ? (
                    <>
                      <Button loading={renderActionLoading} onClick={() => void handleResumeRender(true)}>
                        一键全部生成剩余片段
                      </Button>
                      <Button type="primary" loading={renderActionLoading} onClick={() => void handleResumeRender(false)}>
                        继续生成下一段
                      </Button>
                    </>
                  ) : null}
                  {canResumeRender && !awaitingClipConfirmation ? (
                    <Button type="primary" loading={renderActionLoading} onClick={() => void handleResumeRender()}>
                      继续任务
                    </Button>
                  ) : null}
                  {canCancelRender ? (
                    <Button danger loading={renderActionLoading} onClick={handleCancelRender}>
                      取消任务
                    </Button>
                  ) : null}
                  {canRetryRender ? (
                    <Button loading={renderActionLoading || renderStarting} onClick={handleRetryRender}>
                      重试任务
                    </Button>
                  ) : null}
                </div>
              </Space>
            ) : (
              <div style={{ padding: '72px 0', textAlign: 'center' }}>
                <Spin size="large" />
                <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>渲染任务启动中</Paragraph>
              </div>
            )}
          </Card>

          {renderStatus?.clips?.length ? (
            <Card title="片段生成结果">
              <Collapse
                accordion
                items={renderStatus.clips.map((clip: RenderClipResult) => ({
                  key: String(clip.clip_number),
                  label: (
                    <Space wrap>
                      <Tag color="processing">片段 {clip.clip_number}</Tag>
                      <Text>{clip.title}</Text>
                      <Tag>{clip.duration} 秒</Tag>
                      <Tag color={statusColorMap[clip.status] || 'default'}>{clip.status}</Tag>
                    </Space>
                  ),
                  children: (
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      <Paragraph style={{ marginBottom: 0 }}>{clip.description}</Paragraph>
                      <PreviewAsset assetUrl={clip.asset_url} assetType={clip.asset_type} title={clip.title} />
                      {clip.error ? <Alert type="error" showIcon message="该片段生成失败" description={clip.error} /> : null}
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
                        <Button
                          disabled={!clip.asset_url}
                          icon={<DownloadOutlined />}
                          onClick={() => downloadAsset(clip.asset_url, clip.asset_filename || `${clip.title}.mp4`)}
                        >
                          下载该片段
                        </Button>
                        <Button
                          loading={renderActionLoading}
                          disabled={!canRetrySingleClip || clip.status === 'processing' || clip.status === 'queued'}
                          onClick={() => void handleRetryRenderClip(clip.clip_number)}
                        >
                          重生成该片段
                        </Button>
                      </div>
                      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {clip.video_prompt}
                      </Paragraph>
                    </Space>
                  ),
                }))}
              />
            </Card>
          ) : null}

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Button onClick={() => setCurrentStep(3)}>返回参数</Button>
            <Space wrap>
              <Button
                loading={renderStarting}
                disabled={!segments.length}
                onClick={() => void confirmRestartRender(false)}
              >
                重新从第一段开始生成
              </Button>
              <Button
                loading={renderStarting}
                disabled={!segments.length}
                onClick={() => void confirmRestartRender(true)}
              >
                一键全部重新生成
              </Button>
              {canRetryRender ? (
                <Button loading={renderActionLoading || renderStarting} onClick={handleRetryRender}>
                  重试任务
                </Button>
              ) : null}
              <Button type="primary" disabled={renderStatus?.status !== 'completed'} onClick={() => setCurrentStep(5)}>
                查看最终结果
              </Button>
            </Space>
          </div>
        </Space>
      )
    }

    return (
      <Space direction="vertical" size={20} style={{ width: '100%' }}>
        <Card title="最终成片">
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <PreviewAsset assetUrl={finalPreviewUrl} assetType={finalPreviewType} title={`${projectTitle} 最终合成`} />
            <Text type="secondary">合成文件：{renderStatus?.final_output?.asset_filename || '尚未生成'}</Text>
            <Text type="secondary">
              输出类型：{renderStatus?.final_output?.output_mode === 'video' ? '正式成片' : '快速预览'}
            </Text>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                disabled={!finalPreviewUrl}
                onClick={() =>
                  downloadAsset(
                    finalPreviewUrl,
                    renderStatus?.final_output?.asset_filename || `${projectTitle || 'final_output'}.mp4`,
                  )
                }
              >
                下载最终成片
              </Button>
            </div>
          </Space>
        </Card>

        {shouldPromptSaveTemporaryCharacters ? (
          <Card
            title={`保存临时角色 (${temporaryCharacterSaveEntries.length})`}
            extra={<Text type="secondary">这些临时角色已经参与本次视频生成，可按首次出场首帧造型入库</Text>}
          >
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Alert
                type="info"
                showIcon
                message="保存后会进入正式角色档案库"
                description="本次保存会直接使用该角色首次出场片段的首帧作为参考图，不再额外生成三视图或面部特写。"
              />
              {temporaryCharacterSaveEntries.map(({ profile, firstFrameReference }) => (
                <Card
                  key={profile.id}
                  type="inner"
                  size="small"
                  extra={
                    <Button
                      size="small"
                      type="primary"
                      loading={savingTemporaryCharacterIds.includes(profile.id)}
                      disabled={!firstFrameReference?.asset_url}
                      onClick={() => void handleSaveTemporaryCharacter(profile, firstFrameReference)}
                    >
                      保存到角色档案库
                    </Button>
                  }
                >
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Space wrap>
                      <Text strong>{profile.name}</Text>
                      {profile.role ? <Tag color="processing">{profile.role}</Tag> : null}
                      <Tag color="gold">临时角色</Tag>
                    </Space>
                    {profile.llm_summary ? <Text type="secondary">{profile.llm_summary}</Text> : null}
                    {firstFrameReference?.asset_url ? (
                      <>
                        <PreviewAsset
                          assetUrl={firstFrameReference.asset_url}
                          thumbnailUrl={firstFrameReference.thumbnail_url}
                          assetType={firstFrameReference.asset_type}
                          title={`${profile.name} 首次出场首帧`}
                        />
                        <Text type="secondary">保存时将使用这张首帧作为角色参考图。</Text>
                      </>
                    ) : (
                      <Alert
                        type="warning"
                        showIcon
                        message="暂未找到可保存的首帧参考"
                        description="该角色在当前关键帧结果里还没有可用的首帧图片，暂时不能直接入库。"
                      />
                    )}
                  </Space>
                </Card>
              ))}
            </Space>
          </Card>
        ) : null}

        {renderStatus?.clips?.length ? (
          <Card title="片段明细">
            <Collapse
              accordion
              items={renderStatus.clips.map((clip: RenderClipResult) => ({
                key: String(clip.clip_number),
                label: (
                  <Space wrap>
                    <Tag color="processing">片段 {clip.clip_number}</Tag>
                    <Text>{clip.title}</Text>
                  </Space>
                ),
                children: (
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <PreviewAsset assetUrl={clip.asset_url} assetType={clip.asset_type} title={clip.title} />
                    {clip.error ? <Alert type="error" showIcon message="该片段生成失败" description={clip.error} /> : null}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
                      <Button
                        disabled={!clip.asset_url}
                        icon={<DownloadOutlined />}
                        onClick={() => downloadAsset(clip.asset_url, clip.asset_filename || `${clip.title}.mp4`)}
                      >
                        下载该片段
                      </Button>
                      <Button
                        loading={renderActionLoading}
                        disabled={!canRetrySingleClip || clip.status === 'processing' || clip.status === 'queued'}
                        onClick={() => void handleRetryRenderClip(clip.clip_number)}
                      >
                        重生成该片段
                      </Button>
                    </div>
                  </Space>
                ),
              }))}
            />
          </Card>
        ) : null}

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <Button onClick={() => setCurrentStep(4)}>返回渲染进度</Button>
          <Space wrap>
            <Button
              loading={renderStarting}
              disabled={!segments.length}
              onClick={() => void confirmRestartRender(false)}
            >
              重新从第一段开始生成
            </Button>
            <Button
              loading={renderStarting}
              disabled={!segments.length}
              onClick={() => void confirmRestartRender(true)}
            >
              一键全部重新生成
            </Button>
            {canRetryRender ? (
              <Button loading={renderActionLoading || renderStarting} onClick={handleRetryRender}>
                重试任务
              </Button>
            ) : null}
            <Button type="primary" icon={<RightOutlined />} onClick={handleReset}>
              开始新的项目
            </Button>
          </Space>
        </div>
      </Space>
    )
  }

  if (projectHydrating) {
    return (
      <Card>
        <div style={{ padding: '96px 0', textAlign: 'center' }}>
          <Spin size="large" />
          <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>正在恢复当前项目进度</Paragraph>
        </div>
      </Card>
    )
  }

  const projectStats = [
    { label: '流程', value: workflowMode === WORKFLOW_MODE_LONG_SHOT ? '长镜头' : '标准' },
    { label: '已选角色', value: selectedCharacterIds.length },
    { label: '已选场景', value: selectedSceneIds.length },
    { label: '参考图', value: referenceImages.length },
    { label: '片段数', value: segments.length },
    { label: '关键帧组', value: isLongShotWorkflow ? keyframes.length : '-' },
  ]

  return (
    <div className="pipeline-shell">
      <Card
        className="pipeline-hero-card"
        style={{
          background: 'linear-gradient(135deg, #10233f 0%, #1d4f91 55%, #d8b25a 100%)',
          border: 'none',
        }}
        styles={{ body: { padding: 28 } }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Title level={2} style={{ marginBottom: 8, color: '#fff' }}>
              视频生成主流程
            </Title>
            <Paragraph style={{ color: 'rgba(255,255,255,0.82)', fontSize: 15, marginBottom: 0 }}>
              默认使用标准视频流程；如果你需要首尾帧串联，可以切换到「长镜头视频」作为可选项。
            </Paragraph>
            <Space wrap style={{ marginTop: 16 }}>
              <Tag color="gold">项目：{projectTitle || '未命名项目'}</Tag>
              <Tag color={isLongShotWorkflow ? 'purple' : 'cyan'}>
                流程：{isLongShotWorkflow ? '长镜头视频' : '标准视频'}
              </Tag>
              <Tag color="blue">{selectedProjectId ? `ID: ${selectedProjectId}` : '尚未持久化，编辑后会自动创建草稿'}</Tag>
            </Space>
          </Col>
          <Col>
            <Space>
              <Button icon={<FolderOpenOutlined />} onClick={() => navigate('/projects')}>
                项目列表
              </Button>
              <Button onClick={() => navigate('/characters/library')}>角色档案库</Button>
              <Button icon={<PlusOutlined />} onClick={() => void handleReset()}>
                新建项目
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <Modal
        title="角色确认"
        open={characterConfirmOpen}
        width={860}
        onCancel={() => setCharacterConfirmOpen(false)}
        footer={
          <Space wrap>
            <Button onClick={() => setCharacterConfirmOpen(false)}>取消</Button>
            <Button onClick={() => navigate('/characters/library')}>去角色档案库</Button>
            <Button
              type="primary"
              loading={characterConfirmMode === 'generate_script' ? scriptLoading : splitLoading}
              onClick={() => void handleConfirmCharactersAndContinue()}
            >
              {characterConfirmMode === 'generate_script' ? '确认角色并生成剧本' : '确认角色并生成分段'}
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {characterPrepareResult?.character_resolution?.message ? (
            <Alert
              type={characterPrepareResult.character_resolution.needs_user_action ? 'warning' : 'info'}
              showIcon
              message="本次角色分析结果"
              description={characterPrepareResult.character_resolution.message}
            />
          ) : null}

          <Card
            size="small"
            title={`已保存角色 (${characterPrepareResult?.library_character_profiles?.length || 0})`}
            extra={
              <Text type="secondary">
                {characterConfirmMode === 'generate_script'
                  ? '勾选后会参与本次剧本生成'
                  : isLongShotWorkflow
                    ? '勾选后会参与后续分段、关键帧和视频生成'
                    : '勾选后会参与后续分段和视频生成'}
              </Text>
            }
          >
            {characterPrepareResult?.library_character_profiles?.length ? (
              <Checkbox.Group
                style={{ width: '100%' }}
                value={confirmedLibraryCharacterIds}
                onChange={(values) => setConfirmedLibraryCharacterIds(values as string[])}
              >
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  {characterPrepareResult.library_character_profiles.map((profile) => (
                    <Card key={profile.id} type="inner" size="small">
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <Checkbox value={profile.id}>
                          <Space wrap>
                            <Text strong>{profile.name}</Text>
                            {profile.role ? <Tag color="processing">{profile.role}</Tag> : null}
                            <Tag color="success">正式档案</Tag>
                          </Space>
                        </Checkbox>
                        {profile.llm_summary ? <Text type="secondary">{profile.llm_summary}</Text> : null}
                        {profile.must_keep.length ? <Text type="secondary">必须保持：{profile.must_keep.join('、')}</Text> : null}
                      </Space>
                    </Card>
                  ))}
                </Space>
              </Checkbox.Group>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未匹配到已保存角色" />
            )}
          </Card>

          <Card
            size="small"
            title={`自动生成角色建议 (${characterPrepareResult?.temporary_character_profiles?.length || 0})`}
            extra={
              <Text type="secondary">
                {isLongShotWorkflow
                  ? '仅用于本次创作；生成视频后可按首帧造型保存到角色库'
                  : '仅用于本次创作；标准流程默认不生成角色首帧锚点'}
              </Text>
            }
          >
            {characterPrepareResult?.temporary_character_profiles?.length ? (
              <Checkbox.Group
                style={{ width: '100%' }}
                value={confirmedTemporaryCharacterIds}
                onChange={(values) => setConfirmedTemporaryCharacterIds(values as string[])}
              >
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  {characterPrepareResult.temporary_character_profiles.map((profile) => (
                    <Card key={profile.id} type="inner" size="small">
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <Checkbox value={profile.id}>
                          <Space wrap>
                            <Text strong>{profile.name}</Text>
                            {profile.role ? <Tag color="processing">{profile.role}</Tag> : null}
                            <Tag color="gold">临时角色</Tag>
                          </Space>
                        </Checkbox>
                        {profile.llm_summary ? <Text type="secondary">{profile.llm_summary}</Text> : null}
                        {profile.must_keep.length ? <Text type="secondary">必须保持：{profile.must_keep.join('、')}</Text> : null}
                      </Space>
                    </Card>
                  ))}
                </Space>
              </Checkbox.Group>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未生成角色建议" />
            )}
          </Card>

          <Alert
            type="info"
            showIcon
            message="确认说明"
            description={
              characterConfirmMode === 'generate_script'
                ? '你勾选的已保存角色和角色建议会一起进入本次剧本生成。未勾选的角色不会参与生成。'
                : isLongShotWorkflow
                  ? '你勾选的已保存角色和角色建议会进入后续分段、关键帧和视频生成。未勾选的角色不会参与后续流程。'
                  : '你勾选的已保存角色和角色建议会进入后续分段和视频生成。未勾选的角色不会参与后续流程。'
            }
          />
        </Space>
      </Modal>

      <Card className="pipeline-flow-card" styles={{ body: { padding: 20 } }}>
        <div className="pipeline-flow-header">
          <div>
            <Text type="secondary">流程导航</Text>
            <div className="pipeline-flow-header__title">{stepItems[currentStep]?.title}</div>
            <div className="pipeline-flow-header__subtitle">{stepItems[currentStep]?.subtitle}</div>
          </div>
          <Tag color="processing">STEP {currentStep + 1} / {stepItems.length}</Tag>
        </div>

        <div className="pipeline-flow-switcher">
          <Button
            shape="circle"
            icon={<LeftOutlined />}
            disabled={currentStep === 0}
            onClick={() => {
              setTransitionDirection('backward')
              setCurrentStep(previousStepIndex)
            }}
          />

          <div className="pipeline-flow-track" ref={flowTrackRef}>
            {stepItems.map((item, index) => {
              const active = index === currentStep
              const finished = index < currentStep
              const available = isStepAvailable(index)

              return (
                <button
                  key={item.title}
                  type="button"
                  ref={(element) => {
                    stepButtonRefs.current[index] = element
                  }}
                  className={[
                    'pipeline-flow-step',
                    active ? 'is-active' : '',
                    finished ? 'is-finished' : '',
                    !available ? 'is-disabled' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => goToStep(index)}
                  disabled={!available}
                >
                  <span className="pipeline-flow-step__number">{String(index + 1).padStart(2, '0')}</span>
                  <span className="pipeline-flow-step__content">
                    <span className="pipeline-flow-step__title">
                      <span className="pipeline-flow-step__icon">{item.icon}</span>
                      {item.title}
                    </span>
                    <span className="pipeline-flow-step__subtitle">{item.subtitle}</span>
                  </span>
                </button>
              )
            })}
          </div>

          <Button
            shape="circle"
            icon={<RightOutlined />}
            disabled={currentStep >= stepItems.length - 1 || !isStepAvailable(nextStepIndex)}
            onClick={() => {
              setTransitionDirection('forward')
              goToStep(nextStepIndex)
            }}
          />
        </div>

        <div className="pipeline-flow-footer">
          <div className="pipeline-flow-stats">
            {projectStats.map((item) => (
              <div className="pipeline-flow-stat" key={item.label}>
                <span className="pipeline-flow-stat__label">{item.label}</span>
                <span className="pipeline-flow-stat__value">{item.value}</span>
              </div>
            ))}
          </div>

          <div className="pipeline-flow-meta">
            <div className="pipeline-flow-meta__item">
              <span className="pipeline-flow-meta__label">项目</span>
              <span className="pipeline-flow-meta__value">{projectTitle || '未命名项目'}</span>
            </div>
            <div className="pipeline-flow-meta__item">
              <span className="pipeline-flow-meta__label">风格</span>
              <span className="pipeline-flow-meta__value">{stylePreference || '未设置'}</span>
            </div>
            {renderStatus ? (
              <div className="pipeline-flow-meta__item">
                <span className="pipeline-flow-meta__label">任务</span>
                <span className="pipeline-flow-meta__value">
                  <Tag color={statusColorMap[renderStatus.status] || 'default'}>{renderStatus.status}</Tag>
                  <Tag>{renderStatus.current_step}</Tag>
                </span>
              </div>
            ) : null}
          </div>
        </div>
      </Card>

      <div className="pipeline-stage">
        <div
          key={`step-${currentStep}`}
          className={[
            'pipeline-stage__content',
            transitionDirection === 'forward' ? 'is-forward' : 'is-backward',
          ].join(' ')}
        >
          {renderStepContent()}
        </div>
      </div>
    </div>
  )
}
