import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Row,
  Space,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  AudioOutlined,
  DeleteOutlined,
  EyeOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
  SoundOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import type { UploadFile, UploadProps } from 'antd'
import { useNavigate } from 'react-router-dom'
import { CharacterAssetNav } from '../components/CharacterAssetNav'
import { KlingCollectionResponse, KlingEntityRecord, klingApi } from '../services/api'

const { Title, Paragraph, Text } = Typography
const { TextArea, Search } = Input

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const getStringField = (record: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
    if (typeof value === 'number') {
      return String(value)
    }
  }
  return ''
}

const flattenKlingVoiceRecords = (payload: unknown): KlingEntityRecord[] => {
  if (Array.isArray(payload)) {
    const flattened: KlingEntityRecord[] = []
    for (const item of payload) {
      flattened.push(...flattenKlingVoiceRecords(item))
    }
    return flattened
  }

  if (!isRecord(payload)) {
    return []
  }

  const taskResult = payload.task_result
  if (isRecord(taskResult)) {
    const nestedVoices = taskResult.voices
    if (Array.isArray(nestedVoices)) {
      return flattenKlingVoiceRecords(nestedVoices)
    }
  }

  for (const key of ['items', 'list', 'records', 'voices', 'data']) {
    const value = payload[key]
    if (Array.isArray(value) || isRecord(value)) {
      const nested = flattenKlingVoiceRecords(value)
      if (nested.length) {
        return nested
      }
    }
  }

  const voiceId = getStringField(payload, ['voice_id', 'id'])
  const voiceName = getStringField(payload, ['name', 'voice_name', 'title'])
  const previewUrl = getStringField(payload, ['preview_url', 'demo_url', 'sample_url', 'audio_url', 'trial_url', 'url'])
  if (voiceId || voiceName || previewUrl) {
    return [payload]
  }

  return []
}

const normalizeKlingItems = (payload: KlingCollectionResponse | KlingEntityRecord | unknown): KlingEntityRecord[] => {
  return flattenKlingVoiceRecords(payload)
}

const getVoiceId = (item: KlingEntityRecord) => getStringField(item, ['voice_id', 'id'])
const getVoiceName = (item: KlingEntityRecord) => getStringField(item, ['name', 'voice_name', 'title'])
const getVoiceStatus = (item: KlingEntityRecord) => getStringField(item, ['status', 'train_status', 'state'])
const getVoiceSummary = (item: KlingEntityRecord) =>
  getStringField(item, ['description', 'summary', 'prompt_text', 'text'])
const getVoiceLanguage = (item: KlingEntityRecord) => getStringField(item, ['language', 'lang', 'locale'])
const getVoiceOwner = (item: KlingEntityRecord) => getStringField(item, ['owned_by', 'owner', 'provider', 'vendor'])
const getVoiceGender = (item: KlingEntityRecord) => getStringField(item, ['gender', 'gender_presentation', 'sex'])
const getVoiceStyle = (item: KlingEntityRecord) =>
  getStringField(item, ['style', 'tone', 'emotion_style', 'speaking_style', 'category'])
const getVoicePreviewUrl = (item: KlingEntityRecord) =>
  getStringField(item, ['preview_url', 'demo_url', 'sample_url', 'audio_url', 'trial_url', 'url'])

const getVoiceTags = (item: KlingEntityRecord) => {
  const tags: string[] = []
  for (const key of ['tags', 'labels', 'keywords']) {
    const value = item[key]
    if (!Array.isArray(value)) {
      continue
    }
    for (const tag of value) {
      const normalized = String(tag || '').trim()
      if (normalized && !tags.includes(normalized)) {
        tags.push(normalized)
      }
    }
  }
  return tags
}

const parseExtraBody = (rawText: string) => {
  const normalized = rawText.trim()
  if (!normalized) {
    return {}
  }
  const parsed = JSON.parse(normalized) as unknown
  if (!isRecord(parsed)) {
    throw new Error('附加参数必须是 JSON 对象')
  }
  return parsed
}

const fileToDataUrl = async (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result)
        return
      }
      reject(new Error('音频读取失败'))
    }
    reader.onerror = () => reject(new Error('音频读取失败'))
    reader.readAsDataURL(file)
  })

export const CharacterVoicePage: React.FC = () => {
  const navigate = useNavigate()
  const [customVoices, setCustomVoices] = useState<KlingEntityRecord[]>([])
  const [presetVoices, setPresetVoices] = useState<KlingEntityRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState<KlingEntityRecord | null>(null)
  const [customKeyword, setCustomKeyword] = useState('')
  const [presetKeyword, setPresetKeyword] = useState('')
  const [voiceName, setVoiceName] = useState('')
  const [voiceAlias, setVoiceAlias] = useState('')
  const [voiceText, setVoiceText] = useState('')
  const [promptText, setPromptText] = useState('')
  const [extraJson, setExtraJson] = useState('')
  const [audioFileList, setAudioFileList] = useState<UploadFile[]>([])
  const [audioDataUrl, setAudioDataUrl] = useState('')

  const loadData = async () => {
    setLoading(true)
    try {
      const [customResponse, presetResponse] = await Promise.all([
        klingApi.listCustomVoices({ page_size: 100 }),
        klingApi.listPresetVoices({ page_size: 100 }),
      ])
      setCustomVoices(normalizeKlingItems(customResponse.data))
      setPresetVoices(normalizeKlingItems(presetResponse.data))
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色音色页面加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const uploadProps: UploadProps = {
    accept: 'audio/*',
    beforeUpload: (file) => {
      void fileToDataUrl(file)
        .then((encoded) => {
          setAudioDataUrl(encoded)
          setAudioFileList([
            {
              uid: file.uid,
              name: file.name,
              status: 'done',
              originFileObj: file,
            },
          ])
        })
        .catch((error: unknown) => {
          message.error(error instanceof Error ? error.message : '音频读取失败')
        })
      return false
    },
    fileList: audioFileList,
    onRemove: () => {
      setAudioFileList([])
      setAudioDataUrl('')
    },
  }

  const filteredCustomVoices = useMemo(() => {
    const keyword = customKeyword.trim().toLowerCase()
    if (!keyword) {
      return customVoices
    }
    return customVoices.filter((item) => {
      const haystack = [getVoiceId(item), getVoiceName(item), getVoiceStatus(item), getVoiceSummary(item)]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(keyword)
    })
  }, [customKeyword, customVoices])

  const filteredPresetVoices = useMemo(() => {
    const keyword = presetKeyword.trim().toLowerCase()
    if (!keyword) {
      return presetVoices
    }
    return presetVoices.filter((item) => {
      const haystack = [getVoiceId(item), getVoiceName(item), getVoiceLanguage(item), getVoiceSummary(item)]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(keyword)
    })
  }, [presetKeyword, presetVoices])

  const handleCreateVoice = async () => {
    let extraBody: Record<string, unknown> = {}
    try {
      extraBody = parseExtraBody(extraJson)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '附加参数解析失败')
      return
    }

    if (!voiceName.trim() && !voiceAlias.trim() && !audioDataUrl && !voiceText.trim() && !promptText.trim() && !Object.keys(extraBody).length) {
      message.warning('请至少填写一个音色创建字段')
      return
    }

    setCreating(true)
    try {
      await klingApi.createCustomVoice({
        name: voiceName.trim() || undefined,
        voice_name: voiceAlias.trim() || undefined,
        audio_file: audioDataUrl || undefined,
        text: voiceText.trim() || undefined,
        prompt_text: promptText.trim() || undefined,
        extra_body: extraBody,
      })
      message.success('自定义音色已创建')
      setVoiceName('')
      setVoiceAlias('')
      setVoiceText('')
      setPromptText('')
      setExtraJson('')
      setAudioFileList([])
      setAudioDataUrl('')
      await loadData()
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '自定义音色创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteVoice = async (voiceId: string) => {
    try {
      await klingApi.deleteCustomVoice(voiceId)
      setCustomVoices((previous) => previous.filter((item) => getVoiceId(item) !== voiceId))
      message.success('自定义音色已删除')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '自定义音色删除失败')
    }
  }

  const handleOpenCustomVoiceDetail = async (voiceId: string, fallbackItem: KlingEntityRecord) => {
    setDetailOpen(true)
    setDetailLoading(true)
    setDetailRecord(fallbackItem)
    try {
      const response = await klingApi.getCustomVoice(voiceId)
      setDetailRecord(response.data)
    } catch {
      setDetailRecord(fallbackItem)
    } finally {
      setDetailLoading(false)
    }
  }

  const handleUseVoiceForSubject = (voiceId: string, voiceType: 'custom' | 'preset', voiceLabel: string) => {
    navigate(
      `/characters/subjects?voiceId=${encodeURIComponent(voiceId)}&voiceType=${encodeURIComponent(
        voiceType,
      )}&voiceLabel=${encodeURIComponent(voiceLabel)}`,
    )
  }

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(12,16,30,0.98) 0%, rgba(26,39,86,0.9) 50%, rgba(194,123,48,0.16) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Space direction="vertical" size={6}>
              <Tag color="purple" style={{ width: 'fit-content', margin: 0 }}>
                Character Voices
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                角色音色工作台
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.74)' }}>
                在这里管理可灵官方音色和自定义音色，并把选中的音色直接带回角色主体页使用。
              </Paragraph>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadData()}>
                刷新音色
              </Button>
              <Button icon={<SendOutlined />} type="primary" onClick={() => navigate('/characters/subjects')}>
                去角色主体页
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <CharacterAssetNav current="voices" />

      <Alert
        type="info"
        showIcon
        message="使用方式"
        description="自定义音色页接入可灵音色 API。你可以先创建或筛选音色，再点击“用于主体生成”回到角色主体页，形成完整的角色资产链路。"
      />

      <Row gutter={[20, 20]} align="top">
        <Col xs={24} xl={10}>
          <Card title="创建自定义音色" style={{ borderRadius: 20 }}>
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Input
                placeholder="音色名称 name"
                value={voiceName}
                onChange={(event) => setVoiceName(event.target.value)}
              />
              <Input
                placeholder="别名或 voice_name"
                value={voiceAlias}
                onChange={(event) => setVoiceAlias(event.target.value)}
              />
              <TextArea
                rows={4}
                value={voiceText}
                onChange={(event) => setVoiceText(event.target.value)}
                placeholder="参考文本 text"
              />
              <TextArea
                rows={3}
                value={promptText}
                onChange={(event) => setPromptText(event.target.value)}
                placeholder="补充提示词 prompt_text"
              />
              <Upload {...uploadProps}>
                <Button icon={<UploadOutlined />}>上传参考音频</Button>
              </Upload>
              {audioFileList.length ? <Text type="secondary">已选择音频: {audioFileList[0].name}</Text> : null}
              <TextArea
                rows={5}
                value={extraJson}
                onChange={(event) => setExtraJson(event.target.value)}
                placeholder={'附加参数 JSON，可选\n例如：{"language":"zh","style":"warm"}'}
              />
              <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => void handleCreateVoice()}>
                创建自定义音色
              </Button>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={14}>
          <Card title="音色资源概览" style={{ borderRadius: 20 }}>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Card size="small" style={{ borderRadius: 16 }}>
                  <Space direction="vertical" size={8}>
                    <Tag color="purple" icon={<AudioOutlined />}>
                      自定义音色
                    </Tag>
                    <Title level={3} style={{ margin: 0 }}>
                      {customVoices.length}
                    </Title>
                    <Text type="secondary">可删除、可查看详情、可直接带到主体页。</Text>
                  </Space>
                </Card>
              </Col>
              <Col xs={24} md={12}>
                <Card size="small" style={{ borderRadius: 16 }}>
                  <Space direction="vertical" size={8}>
                    <Tag color="blue" icon={<SoundOutlined />}>
                      官方音色
                    </Tag>
                    <Title level={3} style={{ margin: 0 }}>
                      {presetVoices.length}
                    </Title>
                    <Text type="secondary">适合先选音色，再跳回角色主体页继续生成。</Text>
                  </Space>
                </Card>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      <Card style={{ borderRadius: 20 }}>
        <Tabs
          items={[
            {
              key: 'custom',
              label: `自定义音色 (${customVoices.length})`,
              children: (
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Search
                    allowClear
                    value={customKeyword}
                    onChange={(event) => setCustomKeyword(event.target.value)}
                    placeholder="搜索自定义音色名称、状态或摘要"
                  />
                  {filteredCustomVoices.length ? (
                    <Row gutter={[16, 16]}>
                      {filteredCustomVoices.map((item) => {
                        const voiceId = getVoiceId(item)
                        const voiceLabel = getVoiceName(item) || voiceId || '未命名音色'
                        const previewUrl = getVoicePreviewUrl(item)
                        const owner = getVoiceOwner(item)
                        const language = getVoiceLanguage(item)
                        const voiceStyle = getVoiceStyle(item)
                        return (
                          <Col xs={24} md={12} xl={8} key={voiceId || voiceLabel}>
                            <Card style={{ height: '100%', borderRadius: 18 }}>
                              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                                <Space wrap>
                                  <Tag color="purple">{voiceLabel}</Tag>
                                  {getVoiceStatus(item) ? <Tag color="gold">{getVoiceStatus(item)}</Tag> : null}
                                  {language ? <Tag>{language}</Tag> : null}
                                  {owner ? <Tag color="cyan">{owner}</Tag> : null}
                                </Space>
                                {voiceId ? <Text type="secondary">ID: {voiceId}</Text> : null}
                                {getVoiceSummary(item) ? <Text type="secondary">{getVoiceSummary(item)}</Text> : null}
                                {voiceStyle ? <Text type="secondary">风格: {voiceStyle}</Text> : null}
                                {getVoiceTags(item).length ? (
                                  <Space wrap size={[6, 6]}>
                                    {getVoiceTags(item).slice(0, 4).map((tag) => (
                                      <Tag key={`${voiceId}-${tag}`}>{tag}</Tag>
                                    ))}
                                  </Space>
                                ) : null}
                                {previewUrl ? (
                                  <audio
                                    controls
                                    preload="none"
                                    src={previewUrl}
                                    style={{ width: '100%' }}
                                  />
                                ) : null}
                                <Space wrap>
                                  <Button
                                    size="small"
                                    type="primary"
                                    icon={<SendOutlined />}
                                    onClick={() => handleUseVoiceForSubject(voiceId, 'custom', voiceLabel)}
                                  >
                                    用于主体生成
                                  </Button>
                                  <Button
                                    size="small"
                                    icon={<EyeOutlined />}
                                    onClick={() => void handleOpenCustomVoiceDetail(voiceId, item)}
                                  >
                                    详情
                                  </Button>
                                  <Button
                                    size="small"
                                    danger
                                    icon={<DeleteOutlined />}
                                    onClick={() => void handleDeleteVoice(voiceId)}
                                  >
                                    删除
                                  </Button>
                                  {previewUrl ? (
                                    <Button size="small" icon={<LinkOutlined />} href={previewUrl} target="_blank">
                                      试听
                                    </Button>
                                  ) : null}
                                </Space>
                              </Space>
                            </Card>
                          </Col>
                        )
                      })}
                    </Row>
                  ) : (
                    <Empty description="暂无自定义音色" />
                  )}
                </Space>
              ),
            },
            {
              key: 'preset',
              label: `官方音色 (${presetVoices.length})`,
              children: (
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Search
                    allowClear
                    value={presetKeyword}
                    onChange={(event) => setPresetKeyword(event.target.value)}
                    placeholder="搜索官方音色名称、语言或摘要"
                  />
                  {filteredPresetVoices.length ? (
                    <Row gutter={[16, 16]}>
                      {filteredPresetVoices.map((item) => {
                        const voiceId = getVoiceId(item)
                        const voiceLabel = getVoiceName(item) || voiceId || '未命名官方音色'
                        const previewUrl = getVoicePreviewUrl(item)
                        const owner = getVoiceOwner(item)
                        const gender = getVoiceGender(item)
                        const voiceStyle = getVoiceStyle(item)
                        return (
                          <Col xs={24} md={12} xl={8} key={voiceId || voiceLabel}>
                            <Card style={{ height: '100%', borderRadius: 18 }}>
                              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                                <Space wrap>
                                  <Tag color="blue">{voiceLabel}</Tag>
                                  {getVoiceLanguage(item) ? <Tag>{getVoiceLanguage(item)}</Tag> : null}
                                  {gender ? <Tag color="magenta">{gender}</Tag> : null}
                                  {owner ? <Tag color="cyan">{owner}</Tag> : null}
                                </Space>
                                {voiceId ? <Text type="secondary">ID: {voiceId}</Text> : null}
                                {getVoiceSummary(item) ? <Text type="secondary">{getVoiceSummary(item)}</Text> : null}
                                {voiceStyle ? <Text type="secondary">风格: {voiceStyle}</Text> : null}
                                {getVoiceTags(item).length ? (
                                  <Space wrap size={[6, 6]}>
                                    {getVoiceTags(item).slice(0, 4).map((tag) => (
                                      <Tag key={`${voiceId}-${tag}`}>{tag}</Tag>
                                    ))}
                                  </Space>
                                ) : null}
                                {previewUrl ? (
                                  <audio
                                    controls
                                    preload="none"
                                    src={previewUrl}
                                    style={{ width: '100%' }}
                                  />
                                ) : null}
                                <Space wrap>
                                  <Button
                                    size="small"
                                    type="primary"
                                    icon={<SendOutlined />}
                                    onClick={() => handleUseVoiceForSubject(voiceId, 'preset', voiceLabel)}
                                  >
                                    用于主体生成
                                  </Button>
                                  {previewUrl ? (
                                    <Button size="small" icon={<LinkOutlined />} href={previewUrl} target="_blank">
                                      试听
                                    </Button>
                                  ) : null}
                                </Space>
                              </Space>
                            </Card>
                          </Col>
                        )
                      })}
                    </Row>
                  ) : (
                    <Empty description="暂无官方音色" />
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Drawer
        width={560}
        title="音色详情"
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {detailLoading ? <Alert type="info" showIcon message="正在加载详情..." /> : null}
          {detailRecord ? (
            <>
              <Descriptions bordered column={1} size="small">
                <Descriptions.Item label="音色 ID">{getVoiceId(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="音色名称">{getVoiceName(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="状态">{getVoiceStatus(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="语言">{getVoiceLanguage(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="归属">{getVoiceOwner(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="性别/声线">{getVoiceGender(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="风格">{getVoiceStyle(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="试听链接">
                  {getVoicePreviewUrl(detailRecord) ? (
                    <Button size="small" type="link" href={getVoicePreviewUrl(detailRecord)} target="_blank" icon={<LinkOutlined />}>
                      打开试听
                    </Button>
                  ) : (
                    '-'
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="摘要">{getVoiceSummary(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="标签">
                  {getVoiceTags(detailRecord).length ? (
                    <Space wrap size={[6, 6]}>
                      {getVoiceTags(detailRecord).map((tag) => (
                        <Tag key={`detail-${tag}`}>{tag}</Tag>
                      ))}
                    </Space>
                  ) : (
                    '-'
                  )}
                </Descriptions.Item>
              </Descriptions>
              {getVoicePreviewUrl(detailRecord) ? (
                <Card size="small" title="试听">
                  <audio
                    controls
                    preload="none"
                    src={getVoicePreviewUrl(detailRecord)}
                    style={{ width: '100%' }}
                  />
                </Card>
              ) : null}
              <Card size="small" title="原始返回">
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {JSON.stringify(detailRecord, null, 2)}
                </pre>
              </Card>
            </>
          ) : (
            <Empty description="暂无详情" />
          )}
        </Space>
      </Drawer>
    </Space>
  )
}
