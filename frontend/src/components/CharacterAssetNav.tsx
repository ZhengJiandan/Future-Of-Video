import React from 'react'
import { AppstoreOutlined, AudioOutlined, TeamOutlined } from '@ant-design/icons'
import { Button, Card, Space, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'

const { Text } = Typography

type CharacterAssetTab = 'subjects' | 'library' | 'voices'

interface CharacterAssetNavProps {
  current: CharacterAssetTab
}

const TAB_CONFIG: Array<{
  key: CharacterAssetTab
  label: string
  path: string
  icon: React.ReactNode
  description: string
}> = [
  {
    key: 'subjects',
    label: '角色主体',
    path: '/characters/subjects',
    icon: <AppstoreOutlined />,
    description: '从角色档案抽取稳定主体，作为后续视频生成的直接素材入口。',
  },
  {
    key: 'library',
    label: '角色档案',
    path: '/characters/library',
    icon: <TeamOutlined />,
    description: '沉淀角色设定、参考图和约束信息，作为主体生成和剧本引用的资料底座。',
  },
  {
    key: 'voices',
    label: '角色音色',
    path: '/characters/voices',
    icon: <AudioOutlined />,
    description: '管理官方与自定义音色，并在生成角色主体时直接选择。',
  },
]

export const CharacterAssetNav: React.FC<CharacterAssetNavProps> = ({ current }) => {
  const navigate = useNavigate()
  const currentTab = TAB_CONFIG.find((item) => item.key === current) || TAB_CONFIG[0]

  return (
    <Card style={{ borderRadius: 20 }}>
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Space wrap size={[10, 10]}>
          {TAB_CONFIG.map((item) => (
            <Button
              key={item.key}
              type={item.key === current ? 'primary' : 'default'}
              icon={item.icon}
              onClick={() => navigate(item.path)}
            >
              {item.label}
            </Button>
          ))}
        </Space>
        <Text type="secondary">{currentTab.description}</Text>
      </Space>
    </Card>
  )
}
