import type { LayerGroup, LayerCategory } from './types';
export const OSM_GROUPS: LayerGroup[] = [
  { id: 'transport', label: '🚇 交通', labelEn: '🚇 Transit', categories: [
    { id: 'railway_station', label: '地铁站', labelEn: 'MRT/LRT', icon: '🚇', color: '#E74C3C', dataSource: 'transport/railway_station.geojson' },
    { id: 'bus_stop', label: '公交站', labelEn: 'Bus Stop', icon: '🚌', color: '#E67E22', dataSource: 'transport/bus_stop.geojson' },
  ]},
  { id: 'shopping', label: '🛒 商超', labelEn: '🛒 Shopping', categories: [
    { id: 'mall', label: '商场', labelEn: 'Mall', icon: '🛍️', color: '#8E44AD', dataSource: 'retail/mall.geojson' },
    { id: 'supermarket', label: '超市', labelEn: 'Supermarket', icon: '🛒', color: '#2ECC71', dataSource: 'retail/supermarket.geojson' },
    { id: 'convenience', label: '便利店', labelEn: 'Convenience', icon: '🏪', color: '#27AE60', dataSource: 'retail/convenience.geojson' },
  ]},
  { id: 'food', label: '🍽️ 吃喝', labelEn: '🍽️ Dining', categories: [
    { id: 'restaurant', label: '餐厅', labelEn: 'Restaurant', icon: '🍽️', color: '#E91E63', dataSource: 'food/restaurant.geojson' },
    { id: 'cafe', label: '咖啡厅', labelEn: 'Café', icon: '☕', color: '#795548', dataSource: 'food/cafe.geojson' },
    { id: 'food_court', label: '食阁', labelEn: 'Food Court', icon: '🍜', color: '#FF9800', dataSource: 'food/food_court.geojson' },
  ]},
  { id: 'leisure', label: '🌳 休闲', labelEn: '🌳 Leisure', categories: [
    { id: 'park', label: '公园', labelEn: 'Park', icon: '🌳', color: '#4CAF50', dataSource: 'leisure/park.geojson' },
    { id: 'nature_reserve', label: '自然保护区', labelEn: 'Nature Reserve', icon: '🏞️', color: '#388E3C', dataSource: 'leisure/nature_reserve.geojson' },
    { id: 'sports_centre', label: '体育中心', labelEn: 'Sports Centre', icon: '⚽', color: '#00BCD4', dataSource: 'leisure/sports_centre.geojson' },
  ]},
  { id: 'health', label: '🏥 医疗教育', labelEn: '🏥 Health & Edu', categories: [
    { id: 'hospital', label: '医院', labelEn: 'Hospital', icon: '🏥', color: '#F44336', dataSource: 'health/hospital.geojson' },
    { id: 'clinic', label: '诊所', labelEn: 'Clinic', icon: '🩺', color: '#FF5722', dataSource: 'health/clinic.geojson' },
    { id: 'school', label: '学校', labelEn: 'School', icon: '🏫', color: '#2196F3', dataSource: 'health/school.geojson' },
    { id: 'kindergarten', label: '幼儿园', labelEn: 'Kindergarten', icon: '🎒', color: '#03A9F4', dataSource: 'health/kindergarten.geojson' },
  ]},
  { id: 'service', label: '🏛️ 公共设施', labelEn: '🏛️ Services', categories: [
    { id: 'community_centre', label: '社区中心', labelEn: 'Community Centre', icon: '🏛️', color: '#607D8B', dataSource: 'service/community_centre.geojson' },
    { id: 'post_office', label: '邮局', labelEn: 'Post Office', icon: '📮', color: '#9C27B0', dataSource: 'service/post_office.geojson' },
    { id: 'atm', label: 'ATM', labelEn: 'ATM', icon: '🏧', color: '#3F51B5', dataSource: 'service/atm.geojson' },
    { id: 'bank', label: '银行', labelEn: 'Bank', icon: '🏦', color: '#1A237E', dataSource: 'service/bank.geojson' },
    { id: 'laundry', label: '洗衣店', labelEn: 'Laundry', icon: '🧺', color: '#009688', dataSource: 'service/laundry.geojson' },
  ]},
];
export const ALL_CATEGORIES: LayerCategory[] = OSM_GROUPS.flatMap(g => g.categories);
