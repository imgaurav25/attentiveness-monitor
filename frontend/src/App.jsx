import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import ClassroomDashboard from './pages/ClassroomDashboard'
import PreJoin from './pages/PreJoin'
import MeetingRoom from './pages/MeetingRoom'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/classroom" element={<ClassroomDashboard />} />
      <Route path="/meeting/:meetingId" element={<PreJoin />} />
      <Route path="/meeting/:meetingId/room" element={<MeetingRoom />} />
    </Routes>
  )
}
