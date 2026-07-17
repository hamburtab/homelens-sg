import { SingaporeMap } from './components/singapore-map';
import type { SelectedRegion } from './lib/types';
import './App.css';

function App() {
  const handleSelect = (region: SelectedRegion) => {
    console.log('[SingaporeMap] Selected:', region);
  };

  const handleHover = (region: SelectedRegion | null) => {
    if (region) {
      console.debug('[SingaporeMap] Hover:', region.name);
    }
  };

  return (
    <SingaporeMap
      onSelect={handleSelect}
      onHover={handleHover}
      defaultView="planning"
      listingsUrl="/listings.json"
      listingLabelMap={{
        nearestMRT: 'Nearest MRT',
        postedDate: 'Listed On',
        areaSqft: 'Floor Area',
      }}
    />
  );
}

export default App;
