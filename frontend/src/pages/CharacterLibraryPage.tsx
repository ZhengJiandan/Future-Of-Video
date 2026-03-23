import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Image,
  Input,
  Row,
  Space,
  Tag,
  Typography,
  Upload,
  UploadFile,
  UploadProps,
  message,
} from 'antd'
import {
  EditOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  UploadOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  CharacterImageAnalysisFields,
  CharacterProfile,
  ReferenceImageAsset,
  resolveAssetUrl,
  resolveDisplayAssetUrl,
  scriptPipelineApi,
} from '../services/api'

const { Title, Paragraph, Text } = Typography
const { TextArea } = Input

const emptyCharacterDraft = {
  name: '',
  category: '',
  role: '',
  archetype: '',
  age_range: '',
  gender_presentation: '',
  description: '',
  appearance: '',
  personality: '',
  core_appearance: '',
  hair: '',
  face_features: '',
  body_shape: '',
  outfit: '',
  gear: '',
  color_palette: '',
  visual_do_not_change: '',
  speaking_style: '',
  common_actions: '',
  emotion_baseline: '',
  voice_description: '',
  forbidden_behaviors: '',
  prompt_hint: '',
  llm_summary: '',
  image_prompt_base: '',
  video_prompt_base: '',
  negative_prompt: '',
  tags: '',
  must_keep: '',
  forbidden_traits: '',
  aliases: '',
}

export const CharacterLibraryPage: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const editingCharacterId = searchParams.get('characterId')?.trim() || ''
  const isEditMode = Boolean(editingCharacterId)

  const [initializing, setInitializing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [referenceUploading, setReferenceUploading] = useState(false)
  const [analyzingReference, setAnalyzingReference] = useState(false)
  const [prototypeGenerating, setPrototypeGenerating] = useState(false)
  const [characterDraft, setCharacterDraft] = useState(emptyCharacterDraft)
  const [referenceImage, setReferenceImage] = useState<ReferenceImageAsset | null>(null)
  const [referenceFileList, setReferenceFileList] = useState<UploadFile[]>([])
  const [characterImage, setCharacterImage] = useState<ReferenceImageAsset | null>(null)
  const [characterImagePrompt, setCharacterImagePrompt] = useState('')
  const [refinePrompt, setRefinePrompt] = useState('')

  const profileToDraft = (profile: CharacterProfile) => ({
    name: profile.name || '',
    category: profile.category || '',
    role: profile.role || '',
    archetype: profile.archetype || '',
    age_range: profile.age_range || '',
    gender_presentation: profile.gender_presentation || '',
    description: profile.description || '',
    appearance: profile.appearance || '',
    personality: profile.personality || '',
    core_appearance: profile.core_appearance || '',
    hair: profile.hair || '',
    face_features: profile.face_features || '',
    body_shape: profile.body_shape || '',
    outfit: profile.outfit || '',
    gear: profile.gear || '',
    color_palette: profile.color_palette || '',
    visual_do_not_change: profile.visual_do_not_change || '',
    speaking_style: profile.speaking_style || '',
    common_actions: profile.common_actions || '',
    emotion_baseline: profile.emotion_baseline || '',
    voice_description: profile.voice_description || '',
    forbidden_behaviors: profile.forbidden_behaviors || '',
    prompt_hint: profile.prompt_hint || '',
    llm_summary: profile.llm_summary || '',
    image_prompt_base: profile.image_prompt_base || '',
    video_prompt_base: profile.video_prompt_base || '',
    negative_prompt: profile.negative_prompt || '',
    tags: (profile.tags || []).join(', '),
    must_keep: (profile.must_keep || []).join('\n'),
    forbidden_traits: (profile.forbidden_traits || []).join('\n'),
    aliases: (profile.aliases || []).join(', '),
  })

  const assetFromProfileImage = (
    id: string,
    url: string,
    thumbnailUrl: string | undefined,
    originalFilename: string,
    source: string,
  ): ReferenceImageAsset | null => {
    if (!url) {
      return null
    }
    const filename = url.split('/').pop() || `${id}.png`
    return {
      id,
      url,
      thumbnail_url: thumbnailUrl,
      filename,
      original_filename: originalFilename || filename,
      content_type: 'image/png',
      size: 0,
      source,
    }
  }

  const resetDraft = () => {
    setCharacterDraft(emptyCharacterDraft)
    setReferenceImage(null)
    setReferenceFileList([])
    setCharacterImage(null)
    setCharacterImagePrompt('')
    setRefinePrompt('')
  }

  const exitEditMode = () => {
    resetDraft()
    navigate('/characters/new')
  }

  useEffect(() => {
    if (!editingCharacterId) {
      return
    }

    const loadCharacter = async () => {
      setInitializing(true)
      try {
        const response = await scriptPipelineApi.getCharacter(editingCharacterId)
        const profile = response.data.item
        setCharacterDraft(profileToDraft(profile))

        const imageAsset = assetFromProfileImage(
          profile.id,
          profile.reference_image_url,
          profile.reference_image_thumbnail_url,
          profile.reference_image_original_name,
          'character-library',
        )

        setCharacterImage(imageAsset)
        setReferenceImage(null)
        setReferenceFileList([])
        setCharacterImagePrompt('')
        setRefinePrompt('')
      } catch (requestError: unknown) {
        const responseError = requestError as { response?: { data?: { detail?: string } } }
        message.error(responseError.response?.data?.detail || '角色档案加载失败')
        navigate('/characters/library')
      } finally {
        setInitializing(false)
      }
    }

    void loadCharacter()
  }, [editingCharacterId, navigate])

  const handleDraftChange = (field: keyof typeof emptyCharacterDraft, value: string) => {
    setCharacterDraft((previous) => ({ ...previous, [field]: value }))
  }

  const mergeTextList = (currentValue: string, nextValues: string[]) => {
    const merged = new Set(
      currentValue
        .split(/[，,\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    )
    nextValues.forEach((item) => {
      const normalized = item.trim()
      if (normalized) {
        merged.add(normalized)
      }
    })
    return Array.from(merged).join(', ')
  }

  const applyCharacterAnalysisFields = (fields: CharacterImageAnalysisFields) => {
    let filledCount = 0
    setCharacterDraft((previous) => {
      const next = { ...previous }
      const textKeys = [
        'name',
        'category',
        'role',
        'archetype',
        'age_range',
        'gender_presentation',
        'description',
        'appearance',
        'personality',
        'core_appearance',
        'hair',
        'face_features',
        'body_shape',
        'outfit',
        'gear',
        'color_palette',
        'visual_do_not_change',
        'speaking_style',
        'common_actions',
        'emotion_baseline',
        'forbidden_behaviors',
        'prompt_hint',
        'llm_summary',
        'image_prompt_base',
        'video_prompt_base',
        'negative_prompt',
      ] as const

      textKeys.forEach((key) => {
        const incoming = String(fields[key] || '').trim()
        if (!incoming || String(previous[key] || '').trim()) {
          return
        }
        next[key] = incoming
        filledCount += 1
      })

      const listMappings = [
        ['tags', fields.tags || []],
        ['must_keep', fields.must_keep || []],
        ['forbidden_traits', fields.forbidden_traits || []],
        ['aliases', fields.aliases || []],
      ] as const

      listMappings.forEach(([key, values]) => {
        if (!values.length) {
          return
        }
        const mergedValue = mergeTextList(String(previous[key] || ''), values)
        if (mergedValue !== String(previous[key] || '')) {
          next[key] = mergedValue
          filledCount += 1
        }
      })

      return next
    })
    return filledCount
  }

  const handleAnalyzeReferenceImage = async () => {
    const targetAsset = referenceImage || characterImage
    if (!targetAsset?.url) {
      message.warning('请先上传参考图，再进行图片分析')
      return
    }

    setAnalyzingReference(true)
    try {
      const response = await scriptPipelineApi.analyzeCharacterReference({
        reference_image_url: targetAsset.url,
        reference_image_original_name: targetAsset.original_filename || targetAsset.filename,
      })
      const filledCount = applyCharacterAnalysisFields(response.data.fields)
      if (filledCount > 0) {
        message.success(`图片分析完成，已补充 ${filledCount} 项角色信息`)
      } else {
        message.info('图片分析完成，但当前表单已有内容较完整，未自动覆盖现有信息')
      }
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色图片分析失败')
    } finally {
      setAnalyzingReference(false)
    }
  }

  const handleReferenceUpload: UploadProps['customRequest'] = async (options) => {
    const file = options.file as File
    setReferenceUploading(true)

    try {
      const response = await scriptPipelineApi.uploadCharacterReference(file)
      const asset = response.data
      const uploadItem: UploadFile = {
        uid: asset.id,
        name: asset.original_filename || asset.filename,
        status: 'done',
        url: resolveAssetUrl(asset.url),
        thumbUrl: resolveDisplayAssetUrl(asset.url, asset.thumbnail_url),
      }

      setReferenceImage(asset)
      setCharacterImage(asset)
      setReferenceFileList([uploadItem])
      setCharacterImagePrompt('')
      message.success('角色参考图上传成功')
      options.onSuccess?.(asset)
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      const detail = responseError.response?.data?.detail || '角色参考图上传失败'
      message.error(detail)
      options.onError?.(new Error(detail))
    } finally {
      setReferenceUploading(false)
    }
  }

  const handleReferenceRemove: UploadProps['onRemove'] = () => {
    setReferenceImage(null)
    setCharacterImage(null)
    setReferenceFileList([])
    setCharacterImagePrompt('')
    return true
  }

  const handleGenerateCharacterImage = async () => {
    if (!characterDraft.name.trim() && !referenceImage?.url && !characterImage?.url) {
      message.warning('请先填写角色名称，或先上传一张参考图')
      return
    }

    setPrototypeGenerating(true)
    try {
      const response = await scriptPipelineApi.generateCharacterPrototype({
        base_image_url: characterImage?.url || referenceImage?.url || '',
        name: characterDraft.name.trim(),
        role: characterDraft.role.trim(),
        description: characterDraft.description.trim(),
        appearance: characterDraft.appearance.trim(),
        personality: characterDraft.personality.trim(),
        prompt_hint: characterDraft.prompt_hint.trim(),
        llm_summary: characterDraft.llm_summary.trim(),
        image_prompt_base: characterDraft.image_prompt_base.trim(),
        refine_prompt: refinePrompt.trim(),
      })
      const asset: ReferenceImageAsset = {
        id: response.data.asset_filename,
        url: response.data.asset_url,
        thumbnail_url: response.data.thumbnail_url,
        filename: response.data.asset_filename,
        original_filename: response.data.asset_filename,
        content_type: response.data.asset_type,
        size: 0,
        source: response.data.source,
      }
      setCharacterImage(asset)
      setCharacterImagePrompt(response.data.prompt)
      message.success(refinePrompt.trim() ? '角色图片微调完成' : '角色原型图生成完成')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色图片生成失败')
    } finally {
      setPrototypeGenerating(false)
    }
  }

  const handleCreateCharacter = async () => {
    if (!characterDraft.name.trim()) {
      message.warning('请先填写角色名称')
      return
    }

    const payload = {
      name: characterDraft.name.trim(),
      category: characterDraft.category.trim(),
      role: characterDraft.role.trim(),
      archetype: characterDraft.archetype.trim(),
      age_range: characterDraft.age_range.trim(),
      gender_presentation: characterDraft.gender_presentation.trim(),
      description: characterDraft.description.trim(),
      appearance: characterDraft.appearance.trim(),
      personality: characterDraft.personality.trim(),
      core_appearance: characterDraft.core_appearance.trim(),
      hair: characterDraft.hair.trim(),
      face_features: characterDraft.face_features.trim(),
      body_shape: characterDraft.body_shape.trim(),
      outfit: characterDraft.outfit.trim(),
      gear: characterDraft.gear.trim(),
      color_palette: characterDraft.color_palette.trim(),
      visual_do_not_change: characterDraft.visual_do_not_change.trim(),
      speaking_style: characterDraft.speaking_style.trim(),
      common_actions: characterDraft.common_actions.trim(),
      emotion_baseline: characterDraft.emotion_baseline.trim(),
      voice_description: characterDraft.voice_description.trim(),
      forbidden_behaviors: characterDraft.forbidden_behaviors.trim(),
      prompt_hint: characterDraft.prompt_hint.trim(),
      llm_summary: characterDraft.llm_summary.trim(),
      image_prompt_base: characterDraft.image_prompt_base.trim(),
      video_prompt_base: characterDraft.video_prompt_base.trim(),
      negative_prompt: characterDraft.negative_prompt.trim(),
      tags: characterDraft.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
      must_keep: characterDraft.must_keep.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      forbidden_traits: characterDraft.forbidden_traits.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      aliases: characterDraft.aliases.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      source: 'library',
      reference_image_url: characterImage?.url || referenceImage?.url || '',
      reference_image_original_name: characterImage?.original_filename || referenceImage?.original_filename || '',
    }

    setSaving(true)
    try {
      if (isEditMode) {
        await scriptPipelineApi.updateCharacter(editingCharacterId, payload)
      } else {
        await scriptPipelineApi.createCharacter(payload)
      }
      resetDraft()
      setSearchParams({})
      message.success(isEditMode ? '角色档案已更新' : '角色档案已保存到数据库')
      navigate('/characters/library')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || (isEditMode ? '角色档案更新失败' : '角色档案保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const selectedTagCount = useMemo(
    () =>
      characterDraft.tags
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean).length,
    [characterDraft.tags],
  )

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(11,18,32,0.96) 0%, rgba(20,44,73,0.9) 52%, rgba(186,114,42,0.18) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={17}>
            <Space direction="vertical" size={6}>
              <Tag color="gold" style={{ width: 'fit-content', margin: 0 }}>
                Character Studio
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                {isEditMode ? '角色编辑工作台' : '角色创建工作台'}
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.72)' }}>
                {isEditMode
                  ? '当前正在编辑已保存角色。你可以继续调整设定和角色图，保存后会直接覆盖当前档案。'
                  : '这里专注把角色设定、音色描述和角色图整理完整，再保存成正式档案。已保存角色会单独进入角色库管理。'}
              </Paragraph>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              {isEditMode ? (
                <Button icon={<PlusOutlined />} onClick={exitEditMode}>
                  切换为新建
                </Button>
              ) : null}
              <Button icon={<FolderOpenOutlined />} onClick={() => navigate('/characters/library')}>
                查看已保存角色
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card title={isEditMode ? '编辑角色档案' : '新建角色档案'} style={{ borderRadius: 20 }}>
        <Space direction="vertical" size={18} style={{ width: '100%' }}>
          {isEditMode ? (
            <Alert
              type="warning"
              showIcon
              message="正在编辑角色档案"
              description="当前角色资料已载入，可以继续调整设定、参考图和人物表达设定后保存。"
            />
          ) : null}

          <Alert
            type="info"
            showIcon
            message="建议步骤"
            description="先完善角色设定与音色描述，再上传参考图或生成角色图进行微调。保存后，系统会同步整理角色参考素材，方便后续剧本和视频阶段持续复用。"
          />

          {initializing ? <Alert type="info" showIcon message="正在加载角色档案..." /> : null}

          <Row gutter={[20, 20]} align="top">
            <Col xs={24} xl={14}>
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Card
                  size="small"
                  title="基础信息"
                  extra={<Tag color={isEditMode ? 'gold' : 'blue'}>{isEditMode ? '编辑中' : '新建中'}</Tag>}
                  style={{ borderRadius: 16 }}
                >
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={10}>
                        <Input
                          value={characterDraft.name}
                          onChange={(event) => handleDraftChange('name', event.target.value)}
                          placeholder="角色名称"
                          prefix={<UserOutlined />}
                        />
                      </Col>
                      <Col xs={24} md={7}>
                        <Input
                          value={characterDraft.category}
                          onChange={(event) => handleDraftChange('category', event.target.value)}
                          placeholder="角色分类"
                        />
                      </Col>
                      <Col xs={24} md={7}>
                        <Input
                          value={characterDraft.role}
                          onChange={(event) => handleDraftChange('role', event.target.value)}
                          placeholder="角色定位"
                        />
                      </Col>
                    </Row>

                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={8}>
                        <Input
                          value={characterDraft.archetype}
                          onChange={(event) => handleDraftChange('archetype', event.target.value)}
                          placeholder="角色原型"
                        />
                      </Col>
                      <Col xs={24} md={8}>
                        <Input
                          value={characterDraft.age_range}
                          onChange={(event) => handleDraftChange('age_range', event.target.value)}
                          placeholder="年龄范围"
                        />
                      </Col>
                      <Col xs={24} md={8}>
                        <Input
                          value={characterDraft.gender_presentation}
                          onChange={(event) => handleDraftChange('gender_presentation', event.target.value)}
                          placeholder="性别呈现"
                        />
                      </Col>
                    </Row>

                    <Input
                      value={characterDraft.tags}
                      onChange={(event) => handleDraftChange('tags', event.target.value)}
                      placeholder="标签，多个标签用逗号分隔"
                      suffix={<Text type="secondary">{selectedTagCount} 个</Text>}
                    />

                    <TextArea rows={4} value={characterDraft.description} onChange={(event) => handleDraftChange('description', event.target.value)} placeholder="角色设定" />
                    <TextArea rows={4} value={characterDraft.appearance} onChange={(event) => handleDraftChange('appearance', event.target.value)} placeholder="外观描述" />
                    <TextArea rows={3} value={characterDraft.personality} onChange={(event) => handleDraftChange('personality', event.target.value)} placeholder="性格描述" />
                  </Space>
                </Card>

                <Card size="small" title="视觉锚点" style={{ borderRadius: 16 }}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={12}>
                        <TextArea rows={3} value={characterDraft.core_appearance} onChange={(event) => handleDraftChange('core_appearance', event.target.value)} placeholder="核心外观" />
                      </Col>
                      <Col xs={24} md={12}>
                        <TextArea rows={3} value={characterDraft.visual_do_not_change} onChange={(event) => handleDraftChange('visual_do_not_change', event.target.value)} placeholder="视觉不可变项" />
                      </Col>
                    </Row>

                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={12}>
                        <TextArea rows={2} value={characterDraft.hair} onChange={(event) => handleDraftChange('hair', event.target.value)} placeholder="发型" />
                      </Col>
                      <Col xs={24} md={12}>
                        <TextArea rows={2} value={characterDraft.face_features} onChange={(event) => handleDraftChange('face_features', event.target.value)} placeholder="面部特征" />
                      </Col>
                    </Row>

                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={8}>
                        <TextArea rows={2} value={characterDraft.body_shape} onChange={(event) => handleDraftChange('body_shape', event.target.value)} placeholder="体态" />
                      </Col>
                      <Col xs={24} md={8}>
                        <TextArea rows={2} value={characterDraft.outfit} onChange={(event) => handleDraftChange('outfit', event.target.value)} placeholder="服装" />
                      </Col>
                      <Col xs={24} md={8}>
                        <TextArea rows={2} value={characterDraft.gear} onChange={(event) => handleDraftChange('gear', event.target.value)} placeholder="装备" />
                      </Col>
                    </Row>
                  </Space>
                </Card>

                <Card size="small" title="表演与声音设定" style={{ borderRadius: 16, background: '#fafcff' }}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={12}>
                        <TextArea rows={3} value={characterDraft.speaking_style} onChange={(event) => handleDraftChange('speaking_style', event.target.value)} placeholder="说话方式" />
                      </Col>
                      <Col xs={24} md={12}>
                        <TextArea rows={3} value={characterDraft.common_actions} onChange={(event) => handleDraftChange('common_actions', event.target.value)} placeholder="常见动作" />
                      </Col>
                    </Row>

                    <Row gutter={[12, 12]}>
                      <Col xs={24} md={12}>
                        <TextArea rows={2} value={characterDraft.emotion_baseline} onChange={(event) => handleDraftChange('emotion_baseline', event.target.value)} placeholder="情绪基线" />
                      </Col>
                      <Col xs={24} md={12}>
                        <TextArea rows={2} value={characterDraft.forbidden_behaviors} onChange={(event) => handleDraftChange('forbidden_behaviors', event.target.value)} placeholder="禁止行为" />
                      </Col>
                    </Row>

                    <TextArea
                      rows={4}
                      value={characterDraft.voice_description}
                      onChange={(event) => handleDraftChange('voice_description', event.target.value)}
                      placeholder="音色描述，例如：少女感但不尖锐，气声少，语速平稳，带一点慵懒和好奇心"
                    />
                    <Text type="secondary">
                      这里只记录角色长期稳定的声音设定，用于剧本和视频提示词传递，不直接触发音频合成或试听。
                    </Text>
                  </Space>
                </Card>

                <Card size="small" title="提示词与约束" style={{ borderRadius: 16 }}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Input value={characterDraft.color_palette} onChange={(event) => handleDraftChange('color_palette', event.target.value)} placeholder="配色关键词" />
                    <Input value={characterDraft.aliases} onChange={(event) => handleDraftChange('aliases', event.target.value)} placeholder="别名，多个条目用逗号分隔" />
                    <TextArea rows={2} value={characterDraft.must_keep} onChange={(event) => handleDraftChange('must_keep', event.target.value)} placeholder="必须保持，多个条目用逗号或换行分隔" />
                    <TextArea rows={2} value={characterDraft.forbidden_traits} onChange={(event) => handleDraftChange('forbidden_traits', event.target.value)} placeholder="禁止特征，多个条目用逗号或换行分隔" />
                    <TextArea rows={2} value={characterDraft.prompt_hint} onChange={(event) => handleDraftChange('prompt_hint', event.target.value)} placeholder="给模型的附加提示" />
                    <TextArea rows={2} value={characterDraft.llm_summary} onChange={(event) => handleDraftChange('llm_summary', event.target.value)} placeholder="角色摘要" />
                    <TextArea rows={3} value={characterDraft.image_prompt_base} onChange={(event) => handleDraftChange('image_prompt_base', event.target.value)} placeholder="图片生成基础提示词" />
                    <TextArea rows={3} value={characterDraft.video_prompt_base} onChange={(event) => handleDraftChange('video_prompt_base', event.target.value)} placeholder="视频生成基础提示词" />
                    <TextArea rows={2} value={characterDraft.negative_prompt} onChange={(event) => handleDraftChange('negative_prompt', event.target.value)} placeholder="负向提示词" />
                  </Space>
                </Card>
              </Space>
            </Col>

            <Col xs={24} xl={10}>
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Card size="small" title="当前状态" style={{ borderRadius: 16, background: '#fafcff' }}>
                  <Descriptions column={1} size="small" colon={false}>
                    <Descriptions.Item label="模式">{isEditMode ? '编辑已保存角色' : '新建角色档案'}</Descriptions.Item>
                    <Descriptions.Item label="标签数量">{selectedTagCount} 个</Descriptions.Item>
                    <Descriptions.Item label="参考图">{referenceImage ? '已上传' : '未上传'}</Descriptions.Item>
                    <Descriptions.Item label="角色图">{characterImage?.url ? '已生成或已绑定' : '未生成'}</Descriptions.Item>
                    <Descriptions.Item label="音色描述">
                      {characterDraft.voice_description.trim() || '未填写'}
                    </Descriptions.Item>
                  </Descriptions>
                </Card>

                <Card
                  size="small"
                  title="参考图上传"
                  style={{ borderRadius: 16, background: '#fafcff' }}
                  extra={referenceImage ? <Tag color="green">已上传</Tag> : <Tag>待上传</Tag>}
                >
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Space wrap>
                      <Upload accept="image/*" maxCount={1} customRequest={handleReferenceUpload} onRemove={handleReferenceRemove} fileList={referenceFileList}>
                        <Button icon={<UploadOutlined />} loading={referenceUploading}>
                          上传角色参考图
                        </Button>
                      </Upload>
                      <Button loading={analyzingReference} onClick={handleAnalyzeReferenceImage}>
                        分析图片并补全字段
                      </Button>
                    </Space>
                    {referenceImage ? (
                      <Image
                        src={resolveDisplayAssetUrl(referenceImage.url, referenceImage.thumbnail_url)}
                        alt="角色参考图"
                        style={{ width: '100%', borderRadius: 14, objectFit: 'cover' }}
                        preview={{ src: resolveAssetUrl(referenceImage.url) }}
                      />
                    ) : (
                      <Text type="secondary">如果你已经有角色形象，可以上传后直接保存，也可以先做图片分析，让系统按角色档案字段补充基础信息。</Text>
                    )}
                  </Space>
                </Card>

                <Card
                  size="small"
                  title="角色原型图生成与微调"
                  style={{ borderRadius: 16, background: '#fffdf7' }}
                  extra={characterImage?.url ? <Tag color="gold">已有角色图</Tag> : <Tag>待生成</Tag>}
                >
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <TextArea
                      rows={3}
                      value={refinePrompt}
                      onChange={(event) => setRefinePrompt(event.target.value)}
                      placeholder="可填写你的微调要求，例如：更冷峻、服装更利落、表情更克制"
                    />
                    <Button type="default" loading={prototypeGenerating} onClick={handleGenerateCharacterImage}>
                      {characterImage?.url ? '基于当前图片重新生成 / 微调' : '生成角色原型图'}
                    </Button>
                    {characterImage?.url ? (
                      <>
                        <Image
                          src={resolveDisplayAssetUrl(characterImage.url, characterImage.thumbnail_url)}
                          alt="角色原型图"
                          style={{ width: '100%', borderRadius: 14, objectFit: 'cover' }}
                          preview={{ src: resolveAssetUrl(characterImage.url) }}
                        />
                        {characterImagePrompt ? <Alert type="success" showIcon message="本次角色图描述" description={characterImagePrompt} /> : null}
                      </>
                    ) : (
                      <Text type="secondary">没有上传图片也可以直接生成角色原型图，生成后可继续微调，直到满意为止。</Text>
                    )}
                  </Space>
                </Card>
              </Space>
            </Col>
          </Row>

          <Space wrap>
            <Button
              type="primary"
              icon={isEditMode ? <EditOutlined /> : <PlusOutlined />}
              loading={saving}
              onClick={handleCreateCharacter}
            >
              {isEditMode ? '保存角色修改' : '保存角色档案'}
            </Button>
            <Button onClick={() => navigate('/characters/library')}>返回角色库</Button>
          </Space>
        </Space>
      </Card>
    </Space>
  )
}
