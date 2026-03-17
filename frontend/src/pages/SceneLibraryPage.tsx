import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
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
  EnvironmentOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ReferenceImageAsset, SceneProfile, resolveAssetUrl, scriptPipelineApi } from '../services/api'

const { Title, Paragraph, Text } = Typography
const { TextArea } = Input

const emptySceneDraft = {
  name: '',
  category: '',
  scene_type: '',
  description: '',
  story_function: '',
  location: '',
  scene_rules: '',
  time_setting: '',
  weather: '',
  lighting: '',
  atmosphere: '',
  architecture_style: '',
  color_palette: '',
  prompt_hint: '',
  llm_summary: '',
  image_prompt_base: '',
  video_prompt_base: '',
  negative_prompt: '',
  tags: '',
  allowed_characters: '',
  props_must_have: '',
  props_forbidden: '',
  must_have_elements: '',
  forbidden_elements: '',
  camera_preferences: '',
}

export const SceneLibraryPage: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const editingSceneId = searchParams.get('sceneId')?.trim() || ''
  const isEditMode = Boolean(editingSceneId)
  const [initializing, setInitializing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [referenceUploading, setReferenceUploading] = useState(false)
  const [prototypeGenerating, setPrototypeGenerating] = useState(false)
  const [sceneDraft, setSceneDraft] = useState(emptySceneDraft)
  const [referenceImage, setReferenceImage] = useState<ReferenceImageAsset | null>(null)
  const [referenceFileList, setReferenceFileList] = useState<UploadFile[]>([])
  const [sceneImage, setSceneImage] = useState<ReferenceImageAsset | null>(null)
  const [sceneImagePrompt, setSceneImagePrompt] = useState('')
  const [refinePrompt, setRefinePrompt] = useState('')

  const profileToDraft = (profile: SceneProfile) => ({
    name: profile.name || '',
    category: profile.category || '',
    scene_type: profile.scene_type || '',
    description: profile.description || '',
    story_function: profile.story_function || '',
    location: profile.location || '',
    scene_rules: profile.scene_rules || '',
    time_setting: profile.time_setting || '',
    weather: profile.weather || '',
    lighting: profile.lighting || '',
    atmosphere: profile.atmosphere || '',
    architecture_style: profile.architecture_style || '',
    color_palette: profile.color_palette || '',
    prompt_hint: profile.prompt_hint || '',
    llm_summary: profile.llm_summary || '',
    image_prompt_base: profile.image_prompt_base || '',
    video_prompt_base: profile.video_prompt_base || '',
    negative_prompt: profile.negative_prompt || '',
    tags: (profile.tags || []).join(', '),
    allowed_characters: (profile.allowed_characters || []).join('\n'),
    props_must_have: (profile.props_must_have || []).join('\n'),
    props_forbidden: (profile.props_forbidden || []).join('\n'),
    must_have_elements: (profile.must_have_elements || []).join('\n'),
    forbidden_elements: (profile.forbidden_elements || []).join('\n'),
    camera_preferences: (profile.camera_preferences || []).join('\n'),
  })

  const resetDraft = () => {
    setSceneDraft(emptySceneDraft)
    setReferenceImage(null)
    setReferenceFileList([])
    setSceneImage(null)
    setSceneImagePrompt('')
    setRefinePrompt('')
  }

  const exitEditMode = () => {
    resetDraft()
    setSearchParams({})
  }

  useEffect(() => {
    if (!editingSceneId) {
      return
    }

    const loadScene = async () => {
      setInitializing(true)
      try {
        const response = await scriptPipelineApi.getScene(editingSceneId)
        const profile = response.data.item
        setSceneDraft(profileToDraft(profile))

        if (profile.reference_image_url) {
          const filename = profile.reference_image_url.split('/').pop() || `${profile.id}.png`
          const asset: ReferenceImageAsset = {
            id: profile.id,
            url: profile.reference_image_url,
            filename,
            original_filename: profile.reference_image_original_name || filename,
            content_type: 'image/png',
            size: 0,
            source: 'scene-library',
          }
          setSceneImage(asset)
          setReferenceImage(null)
          setReferenceFileList([])
        } else {
          setReferenceImage(null)
          setReferenceFileList([])
          setSceneImage(null)
        }
        setSceneImagePrompt('')
        setRefinePrompt('')
      } catch (requestError: unknown) {
        const responseError = requestError as { response?: { data?: { detail?: string } } }
        message.error(responseError.response?.data?.detail || '场景档案加载失败')
        setSearchParams({})
      } finally {
        setInitializing(false)
      }
    }

    void loadScene()
  }, [editingSceneId, setSearchParams])

  const handleDraftChange = (field: keyof typeof emptySceneDraft, value: string) => {
    setSceneDraft((previous) => ({ ...previous, [field]: value }))
  }

  const handleReferenceUpload: UploadProps['customRequest'] = async (options) => {
    const file = options.file as File
    setReferenceUploading(true)

    try {
      const response = await scriptPipelineApi.uploadSceneReference(file)
      const asset = response.data
      const uploadItem: UploadFile = {
        uid: asset.id,
        name: asset.original_filename || asset.filename,
        status: 'done',
        url: resolveAssetUrl(asset.url),
      }

      setReferenceImage(asset)
      setSceneImage(asset)
      setReferenceFileList([uploadItem])
      setSceneImagePrompt('')
      message.success('场景参考图上传成功')
      options.onSuccess?.(asset)
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      const detail = responseError.response?.data?.detail || '场景参考图上传失败'
      message.error(detail)
      options.onError?.(new Error(detail))
    } finally {
      setReferenceUploading(false)
    }
  }

  const handleReferenceRemove: UploadProps['onRemove'] = () => {
    setReferenceImage(null)
    setSceneImage(null)
    setReferenceFileList([])
    setSceneImagePrompt('')
    return true
  }

  const handleGenerateSceneImage = async () => {
    if (!sceneDraft.name.trim() && !referenceImage?.url && !sceneImage?.url) {
      message.warning('请先填写场景名称，或先上传一张参考图')
      return
    }

    setPrototypeGenerating(true)
    try {
      const response = await scriptPipelineApi.generateScenePrototype({
        base_image_url: sceneImage?.url || referenceImage?.url || '',
        name: sceneDraft.name.trim(),
        scene_type: sceneDraft.scene_type.trim(),
        description: sceneDraft.description.trim(),
        story_function: sceneDraft.story_function.trim(),
        location: sceneDraft.location.trim(),
        time_setting: sceneDraft.time_setting.trim(),
        weather: sceneDraft.weather.trim(),
        lighting: sceneDraft.lighting.trim(),
        atmosphere: sceneDraft.atmosphere.trim(),
        architecture_style: sceneDraft.architecture_style.trim(),
        color_palette: sceneDraft.color_palette.trim(),
        scene_rules: sceneDraft.scene_rules.trim(),
        prompt_hint: sceneDraft.prompt_hint.trim(),
        llm_summary: sceneDraft.llm_summary.trim(),
        image_prompt_base: sceneDraft.image_prompt_base.trim(),
        refine_prompt: refinePrompt.trim(),
      })
      const asset: ReferenceImageAsset = {
        id: response.data.asset_filename,
        url: response.data.asset_url,
        filename: response.data.asset_filename,
        original_filename: response.data.asset_filename,
        content_type: response.data.asset_type,
        size: 0,
        source: response.data.source,
      }
      setSceneImage(asset)
      setSceneImagePrompt(response.data.prompt)
      message.success(refinePrompt.trim() ? '场景图片微调完成' : '场景原型图生成完成')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '场景图片生成失败')
    } finally {
      setPrototypeGenerating(false)
    }
  }

  const handleSaveScene = async () => {
    if (!sceneDraft.name.trim()) {
      message.warning('请先填写场景名称')
      return
    }

    const payload = {
      name: sceneDraft.name.trim(),
      category: sceneDraft.category.trim(),
      scene_type: sceneDraft.scene_type.trim(),
      description: sceneDraft.description.trim(),
      story_function: sceneDraft.story_function.trim(),
      location: sceneDraft.location.trim(),
      scene_rules: sceneDraft.scene_rules.trim(),
      time_setting: sceneDraft.time_setting.trim(),
      weather: sceneDraft.weather.trim(),
      lighting: sceneDraft.lighting.trim(),
      atmosphere: sceneDraft.atmosphere.trim(),
      architecture_style: sceneDraft.architecture_style.trim(),
      color_palette: sceneDraft.color_palette.trim(),
      prompt_hint: sceneDraft.prompt_hint.trim(),
      llm_summary: sceneDraft.llm_summary.trim(),
      image_prompt_base: sceneDraft.image_prompt_base.trim(),
      video_prompt_base: sceneDraft.video_prompt_base.trim(),
      negative_prompt: sceneDraft.negative_prompt.trim(),
      tags: sceneDraft.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
      allowed_characters: sceneDraft.allowed_characters.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      props_must_have: sceneDraft.props_must_have.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      props_forbidden: sceneDraft.props_forbidden.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      must_have_elements: sceneDraft.must_have_elements.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      forbidden_elements: sceneDraft.forbidden_elements.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      camera_preferences: sceneDraft.camera_preferences.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
      source: 'library',
      reference_image_url: sceneImage?.url || referenceImage?.url || '',
      reference_image_original_name: sceneImage?.original_filename || referenceImage?.original_filename || '',
    }

    setSaving(true)
    try {
      if (isEditMode) {
        await scriptPipelineApi.updateScene(editingSceneId, payload)
      } else {
        await scriptPipelineApi.createScene(payload)
      }
      resetDraft()
      setSearchParams({})
      message.success(isEditMode ? '场景档案已更新' : '场景档案已保存到数据库')
      navigate('/scenes/library')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || (isEditMode ? '场景档案更新失败' : '场景档案保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const selectedTagCount = useMemo(
    () =>
      sceneDraft.tags
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean).length,
    [sceneDraft.tags],
  )

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(20,24,30,0.96) 0%, rgba(26,58,66,0.92) 56%, rgba(84,132,103,0.28) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={17}>
            <Space direction="vertical" size={6}>
              <Tag color="green" style={{ width: 'fit-content', margin: 0 }}>
                Scene Studio
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                {isEditMode ? '场景编辑工作台' : '场景创建工作台'}
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.72)' }}>
                {isEditMode
                  ? '当前正在编辑已保存场景。你可以继续调整地点、时间、天气、氛围和参考图，保存后会直接覆盖当前档案。'
                  : '这里专注做一件事：把场景设定和场景参考图整理到可复用，再保存成正式档案。已保存场景单独放到场景库页面查看。'}
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
              <Button icon={<FolderOpenOutlined />} onClick={() => navigate('/scenes/library')}>
                查看已保存场景
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card title={isEditMode ? '编辑场景档案' : '新建场景档案'} style={{ borderRadius: 20 }}>
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          {isEditMode ? (
            <Alert
              type="warning"
              showIcon
              message="编辑模式"
              description="这个页面已经回填当前场景数据。你可以继续调整场景参考图和约束信息后保存。"
            />
          ) : null}

          <Alert
            type="info"
            showIcon
            message="推荐流程"
            description="先写场景设定。可以上传图片直接作为场景图，也可以先生成场景原型图，再不断微调，满意后保存。"
          />

          {initializing ? <Alert type="info" showIcon message="正在加载场景档案..." /> : null}

          <Row gutter={[12, 12]}>
            <Col span={9}>
              <Input
                value={sceneDraft.name}
                onChange={(event) => handleDraftChange('name', event.target.value)}
                placeholder="场景名称"
                prefix={<EnvironmentOutlined />}
              />
            </Col>
            <Col span={7}>
              <Input
                value={sceneDraft.category}
                onChange={(event) => handleDraftChange('category', event.target.value)}
                placeholder="场景分类"
              />
            </Col>
            <Col span={8}>
              <Input
                value={sceneDraft.scene_type}
                onChange={(event) => handleDraftChange('scene_type', event.target.value)}
                placeholder="场景类型"
              />
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col span={12}>
              <Input
                value={sceneDraft.story_function}
                onChange={(event) => handleDraftChange('story_function', event.target.value)}
                placeholder="剧情功能"
              />
            </Col>
            <Col span={12}>
              <Input
                value={sceneDraft.color_palette}
                onChange={(event) => handleDraftChange('color_palette', event.target.value)}
                placeholder="配色关键词"
              />
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col span={12}>
              <Input
                value={sceneDraft.location}
                onChange={(event) => handleDraftChange('location', event.target.value)}
                placeholder="地点"
              />
            </Col>
            <Col span={12}>
              <Input
                value={sceneDraft.time_setting}
                onChange={(event) => handleDraftChange('time_setting', event.target.value)}
                placeholder="时间设定"
              />
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col span={12}>
              <Input
                value={sceneDraft.weather}
                onChange={(event) => handleDraftChange('weather', event.target.value)}
                placeholder="天气"
              />
            </Col>
            <Col span={12}>
              <Input
                value={sceneDraft.lighting}
                onChange={(event) => handleDraftChange('lighting', event.target.value)}
                placeholder="灯光"
              />
            </Col>
          </Row>

          <Input
            value={sceneDraft.tags}
            onChange={(event) => handleDraftChange('tags', event.target.value)}
            placeholder="标签，多个标签用逗号分隔"
            suffix={<Text type="secondary">{selectedTagCount} 个</Text>}
          />

          <TextArea rows={4} value={sceneDraft.description} onChange={(event) => handleDraftChange('description', event.target.value)} placeholder="场景描述" />
          <TextArea rows={3} value={sceneDraft.atmosphere} onChange={(event) => handleDraftChange('atmosphere', event.target.value)} placeholder="氛围描述" />
          <TextArea rows={2} value={sceneDraft.scene_rules} onChange={(event) => handleDraftChange('scene_rules', event.target.value)} placeholder="场景规则" />
          <TextArea rows={2} value={sceneDraft.architecture_style} onChange={(event) => handleDraftChange('architecture_style', event.target.value)} placeholder="建筑风格" />
          <TextArea rows={2} value={sceneDraft.allowed_characters} onChange={(event) => handleDraftChange('allowed_characters', event.target.value)} placeholder="允许角色，多个条目用逗号或换行分隔" />
          <TextArea rows={2} value={sceneDraft.props_must_have} onChange={(event) => handleDraftChange('props_must_have', event.target.value)} placeholder="必备道具" />
          <TextArea rows={2} value={sceneDraft.props_forbidden} onChange={(event) => handleDraftChange('props_forbidden', event.target.value)} placeholder="禁用道具" />
          <TextArea rows={2} value={sceneDraft.must_have_elements} onChange={(event) => handleDraftChange('must_have_elements', event.target.value)} placeholder="必须元素" />
          <TextArea rows={2} value={sceneDraft.forbidden_elements} onChange={(event) => handleDraftChange('forbidden_elements', event.target.value)} placeholder="禁止元素" />
          <TextArea rows={2} value={sceneDraft.camera_preferences} onChange={(event) => handleDraftChange('camera_preferences', event.target.value)} placeholder="镜头偏好" />

          <Card
            size="small"
            title="1. 上传参考图（可选）"
            style={{ borderRadius: 16, background: '#f7fffb' }}
            extra={referenceImage ? <Tag color="green">已上传</Tag> : <Tag>待上传</Tag>}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Upload
                accept="image/*"
                maxCount={1}
                customRequest={handleReferenceUpload}
                onRemove={handleReferenceRemove}
                fileList={referenceFileList}
              >
                <Button icon={<UploadOutlined />} loading={referenceUploading}>
                  上传场景参考图
                </Button>
              </Upload>
              {referenceImage ? (
                <Image
                  src={resolveAssetUrl(referenceImage.url)}
                  alt="场景参考图"
                  style={{ width: '100%', borderRadius: 14, objectFit: 'cover' }}
                />
              ) : (
                <Text type="secondary">如果你已经有理想场景图，可以上传后直接保存，或者基于它继续微调生成更满意的场景图。</Text>
              )}
            </Space>
          </Card>

          <Card
            size="small"
            title="2. 场景原型图生成与微调"
            style={{ borderRadius: 16, background: '#fffdf7' }}
            extra={sceneImage?.url ? <Tag color="gold">已有场景图</Tag> : <Tag>待生成</Tag>}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <TextArea
                rows={3}
                value={refinePrompt}
                onChange={(event) => setRefinePrompt(event.target.value)}
                placeholder="可填写你的微调要求，例如：更温暖、更有层次、增加雾气、让光线更柔和、构图更紧凑"
              />
              <Button type="default" loading={prototypeGenerating} onClick={handleGenerateSceneImage}>
                {sceneImage?.url ? '基于当前图片重新生成 / 微调' : '生成场景原型图'}
              </Button>
              {sceneImage?.url ? (
                <>
                  <Image
                    src={resolveAssetUrl(sceneImage.url)}
                    alt="场景原型图"
                    style={{ width: '100%', borderRadius: 14, objectFit: 'cover' }}
                  />
                  {sceneImagePrompt ? (
                    <Alert type="success" showIcon message="本次场景图生成 Prompt" description={sceneImagePrompt} />
                  ) : null}
                </>
              ) : (
                <Text type="secondary">没有上传图片也可以直接生成场景原型图，生成后可继续微调，直到满意为止。</Text>
              )}
            </Space>
          </Card>

          <Space wrap>
            <Button
              type="primary"
              icon={isEditMode ? <EditOutlined /> : <PlusOutlined />}
              loading={saving}
              onClick={handleSaveScene}
            >
              {isEditMode ? '保存场景修改' : '保存场景档案'}
            </Button>
            <Button onClick={() => navigate('/scenes/library')}>返回场景库</Button>
          </Space>
        </Space>
      </Card>
    </Space>
  )
}
