import axios from 'axios'
import { getAccessToken, useAuthStore } from '../stores/auth'
import { getTemporaryDoubaoApiKey, useRuntimeSecretsStore } from '../stores/runtimeSecrets'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken()
  const temporaryDoubaoApiKey = getTemporaryDoubaoApiKey()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (temporaryDoubaoApiKey) {
    config.headers['X-Doubao-Api-Key'] = temporaryDoubaoApiKey
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const errorCode =
      error?.response?.headers?.['x-error-code'] ||
      error?.response?.headers?.['X-Error-Code'] ||
      ''
    const detail = error?.response?.data?.detail
    const missingDoubaoApiKey =
      errorCode === 'missing_doubao_api_key' ||
      (typeof detail === 'string' && detail.includes('DOUBAO_API_KEY'))

    if (missingDoubaoApiKey) {
      const reason = typeof detail === 'string' ? detail : '当前调用缺少 DOUBAO_API_KEY。'
      useRuntimeSecretsStore.getState().openApiKeyModal(reason)
    }

    if (error?.response?.status === 401) {
      useAuthStore.getState().logout()
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export interface AuthUser {
  id: string
  email: string
  name: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AuthResponse {
  success: boolean
  message: string
  access_token: string
  token_type: string
  user: AuthUser
}

export interface MeResponse {
  success: boolean
  user: AuthUser
}

export interface CurrentProjectItem {
  id: string
  user_id: string
  project_title: string
  current_step: number
  state: Record<string, unknown>
  status: string
  last_render_task_id: string
  summary: string
  created_at: string
  updated_at: string
}

export interface CurrentProjectResponse {
  success: boolean
  item: CurrentProjectItem | null
}

export interface ProjectListResponse {
  success: boolean
  items: CurrentProjectItem[]
}

export interface ReferenceImageAsset {
  id: string
  url: string
  thumbnail_url?: string
  filename: string
  original_filename: string
  content_type: string
  size: number
  source: string
}

export interface CharacterProfile {
  id: string
  name: string
  category: string
  role: string
  archetype: string
  age_range: string
  gender_presentation: string
  description: string
  appearance: string
  personality: string
  core_appearance: string
  hair: string
  face_features: string
  body_shape: string
  outfit: string
  gear: string
  color_palette: string
  visual_do_not_change: string
  speaking_style: string
  common_actions: string
  emotion_baseline: string
  voice_description: string
  forbidden_behaviors: string
  prompt_hint: string
  llm_summary: string
  image_prompt_base: string
  video_prompt_base: string
  negative_prompt: string
  tags: string[]
  must_keep: string[]
  forbidden_traits: string[]
  aliases: string[]
  profile_version: number
  source: string
  display_image_url?: string
  display_image_thumbnail_url?: string
  reference_image_url: string
  reference_image_thumbnail_url?: string
  reference_image_original_name: string
  three_view_image_url: string
  three_view_image_thumbnail_url?: string
  three_view_prompt: string
  face_closeup_image_url?: string
  face_closeup_image_thumbnail_url?: string
  identity_reference_images?: Array<{
    type: string
    label: string
    url: string
    thumbnail_url?: string
  }>
  identity_anchor_pack?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface SceneProfile {
  id: string
  name: string
  category: string
  scene_type: string
  description: string
  story_function: string
  location: string
  scene_rules: string
  time_setting: string
  weather: string
  lighting: string
  atmosphere: string
  architecture_style: string
  color_palette: string
  prompt_hint: string
  llm_summary: string
  image_prompt_base: string
  video_prompt_base: string
  negative_prompt: string
  tags: string[]
  allowed_characters: string[]
  props_must_have: string[]
  props_forbidden: string[]
  must_have_elements: string[]
  forbidden_elements: string[]
  camera_preferences: string[]
  profile_version: number
  source: string
  reference_image_url: string
  reference_image_thumbnail_url?: string
  reference_image_original_name: string
  created_at: string
  updated_at: string
}

export interface ScriptSummary {
  title: string
  synopsis: string
  total_duration: number
  tone: string
  themes: string[]
  character_count: number
  scene_count: number
}

export interface SegmentDialogueItem {
  text: string
  speaker_name?: string
  speaker_character_id?: string
  emotion?: string
  tone?: string
}

export interface GeneratedScriptResponse {
  success: boolean
  message: string
  processing_time: number
  original_input: string
  style: string
  selected_character_ids: string[]
  selected_scene_ids: string[]
  character_profiles: CharacterProfile[]
  library_character_profiles: CharacterProfile[]
  temporary_character_profiles: CharacterProfile[]
  scene_profiles: SceneProfile[]
  character_resolution?: {
    status?: string
    message?: string
    needs_user_action?: boolean
  }
  reference_images: ReferenceImageAsset[]
  summary: ScriptSummary
  full_script: Record<string, unknown>
  script_text: string
}

export interface PrepareCharactersResponse {
  success: boolean
  message: string
  processing_time: number
  user_input: string
  style: string
  target_total_duration?: number | null
  selected_character_ids: string[]
  active_character_profiles: CharacterProfile[]
  library_character_profiles: CharacterProfile[]
  temporary_character_profiles: CharacterProfile[]
  generation_intent?: Record<string, unknown>
  character_resolution?: {
    status?: string
    message?: string
    needs_user_action?: boolean
  }
}

export interface SegmentItem {
  segment_number: number
  title: string
  description: string
  start_time: number
  end_time: number
  duration: number
  shots_summary: string
  key_actions: string[]
  key_dialogues: SegmentDialogueItem[]
  transition_in: string
  transition_out: string
  continuity_from_prev: string
  continuity_to_next: string
  video_prompt: string
  negative_prompt: string
  generation_config: Record<string, unknown>
  scene_profile_id: string
  scene_profile_version: number
  character_profile_ids: string[]
  character_profile_versions: Record<string, number>
  prompt_focus: string
  contains_primary_character: boolean
  ending_contains_primary_character: boolean
  pre_generate_start_frame: boolean
  start_frame_generation_reason: string
  prefer_primary_character_end_frame: boolean
  new_character_profile_ids: string[]
  handoff_character_profile_ids: string[]
  ending_contains_handoff_characters: boolean
  prefer_character_handoff_end_frame: boolean
  video_url: string
  status: string
}

export interface SegmentValidationCheck {
  code: string
  label: string
  status: 'pass' | 'warning' | 'fail' | string
  detail: string
}

export interface SegmentValidationReview {
  segment_number: number
  title: string
  duration: number
  status: 'pass' | 'warning' | 'fail' | string
  summary: string
  issues: string[]
  suggestions: string[]
}

export interface SplitValidationReport {
  status: 'pass' | 'warning' | 'fail' | string
  summary: string
  checks: SegmentValidationCheck[]
  issues: string[]
  suggestions: string[]
  segment_reviews: SegmentValidationReview[]
  source?: string
  target_total_duration?: number | null
  actual_total_duration?: number
}

export interface SplitScriptResponse {
  success: boolean
  message: string
  processing_time: number
  script_text: string
  total_duration: number
  segment_count: number
  continuity_points: Array<Record<string, unknown>>
  segments: SegmentItem[]
  validation_report?: SplitValidationReport | null
}

export interface KeyframeAsset {
  asset_url: string
  thumbnail_url?: string
  asset_type: string
  asset_filename: string
  prompt: string
  source: string
  status: string
  notes: string
}

export interface SegmentKeyframes {
  segment_number: number
  title: string
  start_frame: KeyframeAsset
  end_frame: KeyframeAsset
  continuity_notes: string
  status: string
}

export interface GenerateKeyframesResponse {
  success: boolean
  message: string
  processing_time: number
  project_title: string
  style: string
  selected_character_ids: string[]
  selected_scene_ids: string[]
  character_profiles: CharacterProfile[]
  scene_profiles: SceneProfile[]
  reference_images: ReferenceImageAsset[]
  keyframes: SegmentKeyframes[]
}

export interface CharacterListResponse {
  success: boolean
  items: CharacterProfile[]
}

export interface CharacterDetailResponse {
  success: boolean
  item: CharacterProfile
}

export interface CharacterMutationResponse extends CharacterProfile {
  success: boolean
  message: string
}

export interface SceneListResponse {
  success: boolean
  items: SceneProfile[]
}

export interface SceneDetailResponse {
  success: boolean
  item: SceneProfile
}

export interface SceneMutationResponse extends SceneProfile {
  success: boolean
  message: string
}

export interface CharacterImageAnalysisFields {
  name: string
  category: string
  role: string
  archetype: string
  age_range: string
  gender_presentation: string
  description: string
  appearance: string
  personality: string
  core_appearance: string
  hair: string
  face_features: string
  body_shape: string
  outfit: string
  gear: string
  color_palette: string
  visual_do_not_change: string
  speaking_style: string
  common_actions: string
  emotion_baseline: string
  forbidden_behaviors: string
  prompt_hint: string
  llm_summary: string
  image_prompt_base: string
  video_prompt_base: string
  negative_prompt: string
  tags: string[]
  must_keep: string[]
  forbidden_traits: string[]
  aliases: string[]
}

export interface SceneImageAnalysisFields {
  name: string
  category: string
  scene_type: string
  description: string
  story_function: string
  location: string
  scene_rules: string
  time_setting: string
  weather: string
  lighting: string
  atmosphere: string
  architecture_style: string
  color_palette: string
  prompt_hint: string
  llm_summary: string
  image_prompt_base: string
  video_prompt_base: string
  negative_prompt: string
  tags: string[]
  allowed_characters: string[]
  props_must_have: string[]
  props_forbidden: string[]
  must_have_elements: string[]
  forbidden_elements: string[]
  camera_preferences: string[]
}

export interface CharacterImageAnalysisResponse {
  success: boolean
  message: string
  fields: CharacterImageAnalysisFields
}

export interface SceneImageAnalysisResponse {
  success: boolean
  message: string
  fields: SceneImageAnalysisFields
}

export interface CharacterThreeViewResponse {
  success: boolean
  message: string
  asset_url: string
  thumbnail_url?: string
  asset_type: string
  asset_filename: string
  prompt: string
  source: string
  status: string
  notes: string
}

export interface CharacterPrototypeResponse {
  success: boolean
  message: string
  asset_url: string
  thumbnail_url?: string
  asset_type: string
  asset_filename: string
  prompt: string
  source: string
  status: string
  notes: string
}

export interface ScenePrototypeResponse {
  success: boolean
  message: string
  asset_url: string
  thumbnail_url?: string
  asset_type: string
  asset_filename: string
  prompt: string
  source: string
  status: string
  notes: string
}

export interface RenderStartResponse {
  success: boolean
  message: string
  task_id: string
  status: string
  current_step: string
  renderer: string
}

export interface RenderClipResult {
  clip_number: number
  title: string
  duration: number
  status: string
  asset_url: string
  asset_type: string
  asset_filename: string
  description: string
  video_prompt: string
  provider: string
  error: string
}

export interface RenderAudioPlanVoice {
  character_id?: string
  name: string
  role?: string
  speaking_style?: string
  emotion_baseline?: string
  voice_description?: string
  voice_direction?: string
}

export interface RenderAudioPlanAmbience {
  scene_profile_id?: string
  name: string
  atmosphere?: string
  lighting?: string
  ambience_direction?: string
}

export interface RenderAudioPlanSegment {
  segment_number: number
  title: string
  duration: number
  characters?: string[]
  voice_tracks?: RenderAudioPlanVoice[]
  dialogue_focus?: string[]
  dialogue_lines?: SegmentDialogueItem[]
  sound_effects?: string[]
  ambience?: string
  music_direction?: string
  transition_hint?: string
  mix_notes?: string[]
}

export interface RenderAudioPlan {
  strategy?: string
  provider_audio_disabled?: boolean
  requested_generate_audio?: boolean
  summary?: string
  mix_principles?: string[]
  character_voice_bible?: RenderAudioPlanVoice[]
  music_bible?: {
    global_direction?: string
    suggested_motifs?: string[]
    avoid?: string[]
  }
  ambience_bible?: RenderAudioPlanAmbience[]
  segment_audio_plan?: RenderAudioPlanSegment[]
}

export interface RenderStatusResponse {
  task_id: string
  project_id?: string
  project_title: string
  status: string
  progress: number
  current_step: string
  renderer: string
  clips: RenderClipResult[]
  final_output: {
    asset_url?: string
    asset_type?: string
    asset_filename?: string
    segment_count?: number
    provider?: string
    output_mode?: string
    video_info?: Record<string, unknown>
  }
  fallback_used?: boolean
  warnings?: string[]
  awaiting_confirmation?: boolean
  last_completed_clip_number?: number | null
  next_clip_number?: number | null
  render_config?: {
    provider?: string
    resolution?: string
    aspect_ratio?: string
    watermark?: boolean
    provider_model?: string
    camera_fixed?: boolean
    generate_audio?: boolean
    requested_generate_audio?: boolean
    audio_strategy?: string
    audio_plan?: RenderAudioPlan | null
    return_last_frame?: boolean
    auto_continue_segments?: boolean
    service_tier?: string
    seed?: number | null
  }
  error: string
  created_at: string
  updated_at: string
}

export const scriptPipelineApi = {
  register: (data: { email: string; password: string; name: string }) =>
    apiClient.post<AuthResponse>('/auth/register', data),
  login: (data: { account?: string; email?: string; password: string }) =>
    apiClient.post<AuthResponse>('/auth/login', data),
  me: () => apiClient.get<MeResponse>('/auth/me'),

  getCurrentProject: () => apiClient.get<CurrentProjectResponse>('/projects/current'),
  listProjects: () => apiClient.get<ProjectListResponse>('/projects'),
  getProject: (projectId: string) => apiClient.get<CurrentProjectResponse>(`/projects/${projectId}`),
  createProject: (data: {
    project_title?: string
    current_step?: number
    state?: Record<string, unknown>
    status?: string
    last_render_task_id?: string
    summary?: string
  }) => apiClient.post<{ success: boolean; message: string; item: CurrentProjectItem }>('/projects', data),
  updateProject: (
    projectId: string,
    data: {
      project_title: string
      current_step: number
      state: Record<string, unknown>
      status?: string
      last_render_task_id?: string
      summary?: string
    },
  ) => apiClient.put<{ success: boolean; message: string; item: CurrentProjectItem }>(`/projects/${projectId}`, data),
  deleteProject: (projectId: string) => apiClient.delete<{ success: boolean; message: string }>(`/projects/${projectId}`),
  saveCurrentProject: (data: {
    project_title: string
    current_step: number
    state: Record<string, unknown>
    status?: string
    last_render_task_id?: string
    summary?: string
  }) => apiClient.put<{ success: boolean; message: string; item: CurrentProjectItem }>('/projects/current', data),
  clearCurrentProject: () => apiClient.delete<{ success: boolean; message: string }>('/projects/current'),

  uploadReferenceImage: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await apiClient.post<ReferenceImageAsset & { success: boolean; message: string }>(
      '/pipeline/upload-reference',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      },
    )
    return response
  },

  listCharacters: () => apiClient.get<CharacterListResponse>('/pipeline/characters'),
  getCharacter: (characterId: string) => apiClient.get<CharacterDetailResponse>(`/pipeline/characters/${characterId}`),
  listScenes: () => apiClient.get<SceneListResponse>('/pipeline/scenes'),
  getScene: (sceneId: string) => apiClient.get<SceneDetailResponse>(`/pipeline/scenes/${sceneId}`),

  uploadCharacterReference: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<ReferenceImageAsset & { success: boolean; message: string }>(
      '/pipeline/characters/upload-reference',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      },
    )
  },

  analyzeCharacterReference: (data: {
    reference_image_url: string
    reference_image_original_name?: string
  }) => apiClient.post<CharacterImageAnalysisResponse>('/pipeline/characters/analyze-reference', data),

  createCharacter: (data: {
    name: string
    category?: string
    role?: string
    archetype?: string
    age_range?: string
    gender_presentation?: string
    description?: string
    appearance?: string
    personality?: string
    core_appearance?: string
    hair?: string
    face_features?: string
    body_shape?: string
    outfit?: string
    gear?: string
    color_palette?: string
    visual_do_not_change?: string
    speaking_style?: string
    common_actions?: string
    emotion_baseline?: string
    voice_description?: string
    forbidden_behaviors?: string
    prompt_hint?: string
    llm_summary?: string
    image_prompt_base?: string
    video_prompt_base?: string
    negative_prompt?: string
    tags?: string[]
    must_keep?: string[]
    forbidden_traits?: string[]
    aliases?: string[]
    profile_version?: number
    source?: string
    reference_image_url?: string
    reference_image_original_name?: string
    three_view_image_url?: string
    three_view_prompt?: string
    face_closeup_image_url?: string
    auto_generate_identity_assets?: boolean
  }) => apiClient.post<CharacterMutationResponse>('/pipeline/characters', data),

  updateCharacter: (
    characterId: string,
    data: {
      name: string
      category?: string
      role?: string
      archetype?: string
      age_range?: string
      gender_presentation?: string
      description?: string
      appearance?: string
      personality?: string
      core_appearance?: string
      hair?: string
      face_features?: string
      body_shape?: string
      outfit?: string
      gear?: string
      color_palette?: string
      visual_do_not_change?: string
      speaking_style?: string
      common_actions?: string
      emotion_baseline?: string
      voice_description?: string
      forbidden_behaviors?: string
      prompt_hint?: string
      llm_summary?: string
      image_prompt_base?: string
      video_prompt_base?: string
      negative_prompt?: string
      tags?: string[]
      must_keep?: string[]
      forbidden_traits?: string[]
      aliases?: string[]
      profile_version?: number
      source?: string
      reference_image_url?: string
      reference_image_original_name?: string
      three_view_image_url?: string
      three_view_prompt?: string
      face_closeup_image_url?: string
      auto_generate_identity_assets?: boolean
    },
  ) => apiClient.put<CharacterMutationResponse>(`/pipeline/characters/${characterId}`, data),

  uploadSceneReference: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<ReferenceImageAsset & { success: boolean; message: string }>(
      '/pipeline/scenes/upload-reference',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      },
    )
  },

  analyzeSceneReference: (data: {
    reference_image_url: string
    reference_image_original_name?: string
  }) => apiClient.post<SceneImageAnalysisResponse>('/pipeline/scenes/analyze-reference', data),

  createScene: (data: {
    name: string
    category?: string
    scene_type?: string
    description?: string
    story_function?: string
    location?: string
    scene_rules?: string
    time_setting?: string
    weather?: string
    lighting?: string
    atmosphere?: string
    architecture_style?: string
    color_palette?: string
    prompt_hint?: string
    llm_summary?: string
    image_prompt_base?: string
    video_prompt_base?: string
    negative_prompt?: string
    tags?: string[]
    allowed_characters?: string[]
    props_must_have?: string[]
    props_forbidden?: string[]
    must_have_elements?: string[]
    forbidden_elements?: string[]
    camera_preferences?: string[]
    profile_version?: number
    source?: string
    reference_image_url?: string
    reference_image_original_name?: string
  }) => apiClient.post<SceneMutationResponse>('/pipeline/scenes', data),

  updateScene: (
    sceneId: string,
    data: {
      name: string
      category?: string
      scene_type?: string
      description?: string
      story_function?: string
      location?: string
      scene_rules?: string
      time_setting?: string
      weather?: string
      lighting?: string
      atmosphere?: string
      architecture_style?: string
      color_palette?: string
      prompt_hint?: string
      llm_summary?: string
      image_prompt_base?: string
      video_prompt_base?: string
      negative_prompt?: string
      tags?: string[]
      allowed_characters?: string[]
      props_must_have?: string[]
      props_forbidden?: string[]
      must_have_elements?: string[]
      forbidden_elements?: string[]
      camera_preferences?: string[]
      profile_version?: number
      source?: string
      reference_image_url?: string
      reference_image_original_name?: string
    },
  ) => apiClient.put<SceneMutationResponse>(`/pipeline/scenes/${sceneId}`, data),

  generateCharacterThreeView: (data: {
    reference_image_url: string
    name?: string
    role?: string
    description?: string
    appearance?: string
    personality?: string
    prompt_hint?: string
  }) => apiClient.post<CharacterThreeViewResponse>('/pipeline/characters/generate-three-view', data),

  generateCharacterPrototype: (data: {
    base_image_url?: string
    name?: string
    role?: string
    description?: string
    appearance?: string
    personality?: string
    prompt_hint?: string
    llm_summary?: string
    image_prompt_base?: string
    refine_prompt?: string
  }) => apiClient.post<CharacterPrototypeResponse>('/pipeline/characters/generate-prototype', data),

  generateScenePrototype: (data: {
    base_image_url?: string
    name?: string
    scene_type?: string
    description?: string
    story_function?: string
    location?: string
    time_setting?: string
    weather?: string
    lighting?: string
    atmosphere?: string
    architecture_style?: string
    color_palette?: string
    scene_rules?: string
    prompt_hint?: string
    llm_summary?: string
    image_prompt_base?: string
    refine_prompt?: string
  }) => apiClient.post<ScenePrototypeResponse>('/pipeline/scenes/generate-prototype', data),

  deleteCharacter: (characterId: string) => apiClient.delete<{ success: boolean; message: string }>(`/pipeline/characters/${characterId}`),
  deleteScene: (sceneId: string) => apiClient.delete<{ success: boolean; message: string }>(`/pipeline/scenes/${sceneId}`),

  generateScript: (data: {
    user_input: string
    style?: string
    target_total_duration?: number
    selected_character_ids?: string[]
    selected_scene_ids?: string[]
    character_profiles?: CharacterProfile[]
    scene_profiles?: SceneProfile[]
    reference_images?: ReferenceImageAsset[]
  }) => apiClient.post<GeneratedScriptResponse>('/pipeline/generate-script', data),

  prepareCharacters: (data: {
    user_input: string
    style?: string
    target_total_duration?: number
    selected_character_ids?: string[]
    character_profiles?: CharacterProfile[]
  }) => apiClient.post<PrepareCharactersResponse>('/pipeline/prepare-characters', data),

  splitScript: (data: {
    script_text: string
    max_segment_duration?: number
    target_total_duration?: number
  }) => apiClient.post<SplitScriptResponse>('/pipeline/split-script', data),

  generateKeyframes: (data: {
    project_title: string
    style?: string
    selected_character_ids?: string[]
    selected_scene_ids?: string[]
    character_profiles?: CharacterProfile[]
    scene_profiles?: SceneProfile[]
    reference_images?: ReferenceImageAsset[]
    segments: SegmentItem[]
  }) => apiClient.post<GenerateKeyframesResponse>('/pipeline/generate-keyframes', data),

  renderProject: (data: {
    project_id?: string
    project_title: string
    provider?: string
    resolution?: string
    aspect_ratio?: string
    watermark?: boolean
    provider_model?: string
    camera_fixed?: boolean
    generate_audio?: boolean
    return_last_frame?: boolean
    auto_continue_segments?: boolean
    service_tier?: string
    seed?: number
    selected_character_ids?: string[]
    selected_scene_ids?: string[]
    character_profiles?: CharacterProfile[]
    scene_profiles?: SceneProfile[]
    segments: SegmentItem[]
    keyframes: SegmentKeyframes[]
  }) => apiClient.post<RenderStartResponse>('/pipeline/render', data),

  getRenderStatus: (taskId: string) => apiClient.get<RenderStatusResponse>(`/pipeline/render/${taskId}`),
  cancelRenderTask: (taskId: string) => apiClient.post<RenderStatusResponse>(`/pipeline/render/${taskId}/cancel`),
  pauseRenderTask: (taskId: string) => apiClient.post<RenderStatusResponse>(`/pipeline/render/${taskId}/pause`),
  resumeRenderTask: (taskId: string, data?: { auto_continue_segments?: boolean | null }) =>
    apiClient.post<RenderStatusResponse>(`/pipeline/render/${taskId}/resume`, data || {}),
  retryRenderClip: (taskId: string, clipNumber: number) =>
    apiClient.post<RenderStatusResponse>(`/pipeline/render/${taskId}/clips/${clipNumber}/retry`),
  retryRenderTask: (taskId: string) => apiClient.post<RenderStartResponse>(`/pipeline/render/${taskId}/retry`),

  healthCheck: () => apiClient.get('/pipeline/health'),
}

export const resolveAssetUrl = (assetUrl?: string) => {
  if (!assetUrl) {
    return ''
  }

  if (assetUrl.startsWith('http://') || assetUrl.startsWith('https://')) {
    return assetUrl
  }

  if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
    const base = new URL(API_BASE_URL)
    return `${base.origin}${assetUrl}`
  }

  return assetUrl
}

export const resolveDisplayAssetUrl = (assetUrl?: string, thumbnailUrl?: string) =>
  resolveAssetUrl(thumbnailUrl || assetUrl)

export default apiClient
