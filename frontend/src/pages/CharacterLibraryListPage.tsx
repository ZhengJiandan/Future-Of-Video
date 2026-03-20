import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Image,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  AudioOutlined,
  DeleteOutlined,
  EditOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  ReloadOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { CharacterProfile, resolveAssetUrl, scriptPipelineApi } from '../services/api'

const { Title, Paragraph, Text } = Typography
const { Search } = Input

export const CharacterLibraryListPage: React.FC = () => {
  const navigate = useNavigate()
  const [characters, setCharacters] = useState<CharacterProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')

  const loadCharacters = async () => {
    setLoading(true)
    try {
      const response = await scriptPipelineApi.listCharacters()
      setCharacters(response.data.items || [])
    } catch {
      message.error('角色档案加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadCharacters()
  }, [])

  const handleDelete = async (characterId: string) => {
    try {
      await scriptPipelineApi.deleteCharacter(characterId)
      setCharacters((previous) => previous.filter((item) => item.id !== characterId))
      message.success('角色档案已删除')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色档案删除失败')
    }
  }

  const categoryOptions = useMemo(
    () =>
      Array.from(new Set(characters.map((item) => item.category).filter(Boolean))).map((item) => ({
        label: item,
        value: item,
      })),
    [characters],
  )

  const filteredCharacters = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()

    return characters.filter((item) => {
      const categoryMatched = categoryFilter === 'all' || item.category === categoryFilter
      if (!categoryMatched) {
        return false
      }

      if (!normalizedKeyword) {
        return true
      }

      const haystack = [
        item.name,
        item.category,
        item.role,
        item.archetype,
        item.description,
        item.appearance,
        item.personality,
        item.llm_summary,
        ...(item.tags || []),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()

      return haystack.includes(normalizedKeyword)
    })
  }, [categoryFilter, characters, keyword])

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(18,23,35,0.96) 0%, rgba(27,54,88,0.9) 52%, rgba(201,152,74,0.22) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Space direction="vertical" size={6}>
              <Tag color="blue" style={{ width: 'fit-content', margin: 0 }}>
                Character Library
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                已保存角色库
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.74)' }}>
                这里专门管理已经入库的角色档案。用于剧本、图片和视频阶段的稳定角色约束，不再和创建工作台混在同一页。
              </Paragraph>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadCharacters()}>
                刷新列表
              </Button>
              <Button icon={<AudioOutlined />} onClick={() => navigate('/voices')}>
                音色目录
              </Button>
              <Button icon={<PlusOutlined />} type="primary" onClick={() => navigate('/characters/new')}>
                新建角色
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card style={{ borderRadius: 20 }}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="使用方式"
            description="先在角色编辑页完善设定和参考图，保存后再回到这里筛选、查看和管理。列表主图会展示当前确认的角色形象。"
          />

          <Row gutter={[12, 12]}>
            <Col xs={24} md={14}>
              <Search
                allowClear
                placeholder="搜索角色名称、定位、原型、标签或设定"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
              />
            </Col>
            <Col xs={24} md={10}>
              <Select
                style={{ width: '100%' }}
                value={categoryFilter}
                onChange={setCategoryFilter}
                options={[
                  { label: '全部分类', value: 'all' },
                  ...categoryOptions,
                ]}
              />
            </Col>
          </Row>

          <Text type="secondary">
            共 {characters.length} 个角色，当前显示 {filteredCharacters.length} 个
          </Text>
        </Space>
      </Card>

      {filteredCharacters.length ? (
        <Row gutter={[20, 20]}>
          {filteredCharacters.map((character) => (
            <Col xs={24} md={12} xl={8} key={character.id}>
              <Card
                hoverable
                style={{ height: '100%', borderRadius: 20 }}
                cover={
                  character.reference_image_url ? (
                    <div
                      style={{
                        height: 280,
                        overflow: 'hidden',
                        background:
                          'radial-gradient(circle at top, rgba(38,74,122,0.24), rgba(14,18,27,0.96))',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: 16,
                      }}
                    >
                      <Image
                        src={resolveAssetUrl(character.reference_image_url)}
                        alt={character.name}
                        style={{ maxHeight: 248, objectFit: 'contain' }}
                        preview
                      />
                    </div>
                  ) : undefined
                }
                actions={[
                  <Button
                    key="edit"
                    type="link"
                    icon={<EditOutlined />}
                    onClick={() => navigate(`/characters/edit?characterId=${character.id}`)}
                  >
                    编辑
                  </Button>,
                  <Button key="create" type="link" icon={<PlusOutlined />} onClick={() => navigate('/characters/new')}>
                    继续创建
                  </Button>,
                  <Button
                    key="delete"
                    type="link"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => void handleDelete(character.id)}
                  >
                    删除
                  </Button>,
                ]}
              >
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag color="processing" icon={<TeamOutlined />}>
                      {character.name}
                    </Tag>
                    {character.category ? <Tag>{character.category}</Tag> : null}
                    {character.role ? <Tag color="purple">{character.role}</Tag> : null}
                    {character.archetype ? <Tag color="gold">{character.archetype}</Tag> : null}
                  </Space>

                  {character.llm_summary ? <Text>{character.llm_summary}</Text> : null}

                  {character.appearance ? (
                    <Text type="secondary">外观: {character.appearance}</Text>
                  ) : null}

                  {character.personality ? (
                    <Text type="secondary">性格: {character.personality}</Text>
                  ) : null}

                  {character.identity_reference_images?.length ? (
                    <Space wrap size={[6, 6]}>
                      {character.identity_reference_images.map((item) => (
                        <Tag key={`${character.id}-${item.type}`} color={item.type === 'face_closeup' ? 'magenta' : item.type === 'three_view' ? 'cyan' : 'default'}>
                          {item.label}
                        </Tag>
                      ))}
                    </Space>
                  ) : null}

                  {character.must_keep?.length ? (
                    <Space wrap size={[6, 6]}>
                      {character.must_keep.map((item) => (
                        <Tag key={`${character.id}-keep-${item}`} color="blue">
                          {item}
                        </Tag>
                      ))}
                    </Space>
                  ) : null}

                  {character.tags?.length ? (
                    <Space wrap size={[6, 6]}>
                      {character.tags.map((item) => (
                        <Tag key={`${character.id}-tag-${item}`}>{item}</Tag>
                      ))}
                    </Space>
                  ) : null}

                  <Text type="secondary">
                    版本 {character.profile_version || 1}
                    {character.reference_image_original_name
                      ? ` · 图源 ${character.reference_image_original_name}`
                      : ''}
                  </Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      ) : (
        <Card style={{ borderRadius: 20 }}>
          <Empty
            description={keyword || categoryFilter !== 'all' ? '没有符合筛选条件的角色' : '还没有已保存角色'}
          >
            <Space>
              <Button icon={<FolderOpenOutlined />} onClick={() => void loadCharacters()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/characters/new')}>
                去创建角色
              </Button>
            </Space>
          </Empty>
        </Card>
      )}
    </Space>
  )
}
